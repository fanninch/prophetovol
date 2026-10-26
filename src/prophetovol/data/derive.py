"""The ivolatility adapter's normalization and derived columns (DATA-13, DATA-14, DATA-15).

Everything runs in the ingest's working database, in this order:

1. :func:`load_files`: the import's CSV files, read as text, parsed into table ``p``.
2. :func:`load_reference`: the root table and a calendar table of trading days.
3. :func:`derive`: table ``n0`` with the derived columns (roots, ``osi_symbol``, settlement date,
   expiry, last trading day, time to expiry, trading days to expiry, internal IV), then the parity
   fits (table ``fits``) and table ``n`` with the forward chosen per DATA-14.
4. :func:`read_partition`: one month of ``n`` as an Arrow table in :data:`~prophetovol.data.schema.MARKET_SCHEMA`,
   with the internal greeks: copied from the vendor from the data source's ``internal_greeks_from``
   date, recomputed with Black-76 before it.

Time to expiry is computed in SQL with the same arithmetic as :mod:`prophetovol.pricing.time`
(whole minutes between exchange clock times, over 525,600); a test checks the two agree row by row.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from prophetovol.core.conventions import DAYS_PER_YEAR, MINUTES_PER_YEAR
from prophetovol.core.errors import ConfigurationError
from prophetovol.data.ivolatility import COLUMNS
from prophetovol.data.schema import MARKET_COLUMNS, MARKET_SCHEMA, GreeksSource
from prophetovol.pricing import black76
from prophetovol.reference.calendar import TradingCalendar
from prophetovol.reference.models import DataSource, Underlying

PARITY_MAX_DISCOUNT = 1.05
"""Largest plausible parity discount factor; a fit above it (or at or below 0) is invalid (DATA-14)."""


def _sql_date(day: date | None) -> str:
    """A date as a SQL literal.

    :param day: The date, or ``None``.
    :returns: ``DATE 'YYYY-MM-DD'`` or ``NULL``.
    """
    return "NULL" if day is None else f"DATE '{day.isoformat()}'"


def _sql_time(clock: time) -> str:
    """A clock time as a SQL literal.

    :param clock: The time.
    :returns: ``TIME 'HH:MM:SS'``.
    """
    return f"TIME '{clock.isoformat()}'"


def open_work_db(path: Path, memory_limit: str) -> duckdb.DuckDBPyConnection:
    """Open the ingest's working database.

    :param path: The database file, inside the import's working folder.
    :param memory_limit: DuckDB's memory limit, for example ``"2GB"``; work beyond it spills to disk.
    :returns: The connection, with instants returned in UTC.
    """
    con = duckdb.connect(str(path))
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{(path.parent / 'spill').as_posix()}'")
    con.execute("SET TimeZone = 'UTC'")
    return con


def load_files(con: duckdb.DuckDBPyConnection, files: list[Path]) -> int:
    """Read the import's CSV files as text and parse them into table ``p``.

    Every vendor column is read as text, so an unparseable value becomes a counted validation finding
    rather than a failed read; the parsed columns are null where parsing failed.

    :param con: The working database.
    :param files: The CSV files, whose headers have already been checked.
    :returns: The number of rows read.
    """
    file_list = "[" + ", ".join(f"'{f.as_posix()}'" for f in files) + "]"
    columns = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in COLUMNS) + "}"
    con.execute(f"""
        CREATE TABLE raw AS SELECT * FROM read_csv({file_list}, header = true, columns = {columns},
            auto_detect = false, delim = ',', quote = '"', filename = true)""")
    con.execute("""
        CREATE TABLE p AS SELECT
            regexp_extract(filename, '[^/\\\\]+$') AS file,
            symbol, exchange,
            "date" AS date_raw, try_strptime("date", '%m/%d/%Y')::DATE AS dt,
            try_cast("adjusted close" AS DOUBLE) AS index_level,
            "option symbol" AS vendor_symbol,
            CASE WHEN length("option symbol") = 5 THEN substr("option symbol", 1, 3)
                 ELSE trim(substr("option symbol", 1, 6)) END AS vendor_root,
            expiration AS ex_raw, try_strptime(expiration, '%m/%d/%Y')::DATE AS ex,
            strike AS strike_raw, try_cast(strike AS DOUBLE) AS strike,
            "call/put" AS cp, style,
            ask AS ask_raw, try_cast(ask AS DOUBLE) AS ask,
            bid AS bid_raw, try_cast(bid AS DOUBLE) AS bid,
            try_cast("mean price" AS DOUBLE) AS vendor_mid,
            try_cast(iv AS DOUBLE) AS iv_raw,
            try_cast(volume AS BIGINT) AS volume,
            try_cast("open interest" AS BIGINT) AS open_interest,
            try_cast("stock price for iv" AS DOUBLE) AS fwd_raw,
            coalesce("*", '') = '*' AS vendor_flag,
            try_cast(delta AS DOUBLE) AS vendor_delta, try_cast(vega AS DOUBLE) AS vendor_vega,
            try_cast(gamma AS DOUBLE) AS vendor_gamma, try_cast(theta AS DOUBLE) AS vendor_theta,
            try_cast(rho AS DOUBLE) AS vendor_rho
        FROM raw""")
    con.execute("DROP TABLE raw")
    return con.execute("SELECT count(*) FROM p").fetchone()[0]


def load_reference(con: duckdb.DuckDBPyConnection, underlying: Underlying | None, calendar: TradingCalendar) -> set[date]:
    """Load the root table and the calendar table covering the import's dates and expirations.

    :param con: The working database, with table ``p``.
    :param underlying: The import's underlying; ``None`` loads an empty root table (the import will
        fail validation on its underlying).
    :param calendar: The trading calendar.
    :returns: The trading days loaded.
    :raises ConfigurationError: If the dates or expirations fall outside the calendar's range.
    """
    con.execute("CREATE TABLE roots (vendor_root VARCHAR, root VARCHAR, settlement_style VARCHAR)")
    if underlying is not None:
        con.executemany("INSERT INTO roots VALUES (?, ?, ?)",
                        [(k, r.normalized_root, r.settlement_style.value) for k, r in sorted(underlying.roots.items())])
    lo, hi = con.execute("SELECT least(min(dt), min(ex)), greatest(max(dt), max(ex)) FROM p").fetchone()
    con.execute("CREATE TABLE sessions (d DATE, idx INTEGER)")
    if lo is None:
        return set()
    start, end = lo - timedelta(days=15), hi + timedelta(days=15)
    if start < calendar.first_day or end > calendar.last_day:
        raise ConfigurationError(f"dates from {lo} to {hi} fall outside the trading calendar's range "
                                 f"{calendar.first_day} to {calendar.last_day}")
    days = calendar.sessions_in_range(start, end)
    con.executemany("INSERT INTO sessions VALUES (?, ?)", [(d, i) for i, d in enumerate(days)])
    return set(days)


def derive(con: duckdb.DuckDBPyConnection, underlying: Underlying, source: DataSource) -> None:
    """Build table ``n``: the normalized rows with every derived column except the internal greeks.

    :param con: The working database, with tables ``p``, ``roots`` and ``sessions``.
    :param underlying: The import's underlying.
    :param source: The data source.
    """
    tz, utz = source.timezone, underlying.timezone
    am, pm = _sql_time(underlying.expiry_time("AM")), _sql_time(underlying.expiry_time("PM"))
    con.execute("""
        CREATE TABLE exps AS
        WITH e AS (SELECT DISTINCT p.ex AS expiration, r.settlement_style FROM p JOIN roots r USING (vendor_root)),
             s AS (SELECT e.expiration, e.settlement_style, s.d AS settlement_date, s.idx AS settle_idx
                   FROM e ASOF JOIN sessions s ON e.expiration >= s.d)
        SELECT s.*, CASE WHEN s.settlement_style = 'AM' THEN prev.d ELSE s.settlement_date END AS last_trading_date
        FROM s LEFT JOIN sessions prev ON prev.idx = s.settle_idx - 1""")
    con.execute("""
        CREATE TABLE days AS
        WITH dd AS (SELECT DISTINCT dt FROM p) SELECT dd.dt, s.idx AS asof_idx FROM dd ASOF JOIN sessions s ON dd.dt >= s.d""")
    con.execute(f"""
        CREATE TABLE n0 AS
        WITH b AS (
            SELECT p.*, r.root, r.settlement_style, x.settlement_date, x.last_trading_date, x.settle_idx, dd.asof_idx,
                   p.dt + {_sql_time(source.option_snapshot_time)} AS as_of_local,
                   x.settlement_date + CASE r.settlement_style WHEN 'AM' THEN {am} ELSE {pm} END AS expiry_local
            FROM p JOIN roots r USING (vendor_root)
            JOIN exps x ON x.expiration = p.ex AND x.settlement_style = r.settlement_style
            JOIN days dd ON dd.dt = p.dt),
        m AS (SELECT *, date_diff('minute', as_of_local, expiry_local) AS minutes FROM b)
        SELECT
            symbol AS underlying, exchange, dt AS as_of_date,
            timezone('{tz}', as_of_local) AS as_of, as_of_local,
            timezone('{tz}', dt + {_sql_time(source.index_snapshot_time)}) AS index_as_of,
            index_level, vendor_symbol, vendor_root, root, settlement_style,
            rpad(root, 6, ' ') || strftime(ex, '%y%m%d') || cp
                || lpad(CAST(CAST(round(strike * 1000) AS BIGINT) AS VARCHAR), 8, '0') AS osi_symbol,
            ex AS expiration, settlement_date,
            timezone('{utz}', expiry_local) AS expiry_timestamp, expiry_local, last_trading_date,
            minutes / {float(MINUTES_PER_YEAR)} AS time_to_expiry_years,
            minutes / {float(MINUTES_PER_YEAR)} * {DAYS_PER_YEAR} AS days_to_expiry,
            CAST(greatest(settle_idx - asof_idx, 0) AS INTEGER) AS trading_days_to_expiry,
            strike, CASE cp WHEN 'C' THEN 'call' ELSE 'put' END AS option_type, style AS exercise_style,
            bid, ask, vendor_mid, volume, open_interest, vendor_flag,
            CASE WHEN iv_raw = -1 THEN NULL ELSE iv_raw END AS vendor_iv,
            CASE WHEN dt >= settlement_date OR iv_raw IS NULL OR iv_raw <= 0 THEN NULL ELSE iv_raw END AS iv,
            CASE WHEN fwd_raw > 0 THEN fwd_raw END AS vendor_forward,
            vendor_delta, vendor_gamma, vendor_vega, vendor_theta, vendor_rho,
            iv_raw, fwd_raw, file
        FROM m""")
    _fit_parity(con, source.parity_strikes)
    cutover = _sql_date(source.per_series_forward_from)
    con.execute(f"""
        CREATE TABLE n AS SELECT n0.*,
            f.parity_strikes, f.parity_forward, f.parity_discount,
            CASE WHEN {cutover} IS NULL OR n0.as_of_date >= {cutover} THEN 'per_series_forward' ELSE 'single_price' END
                AS vendor_methodology,
            CASE WHEN n0.as_of_date >= n0.settlement_date THEN NULL
                 WHEN {cutover} IS NULL OR n0.as_of_date >= {cutover} THEN n0.vendor_forward
                 WHEN f.parity_forward IS NOT NULL THEN f.parity_forward
                 ELSE n0.vendor_forward END AS forward,
            CASE WHEN n0.as_of_date >= n0.settlement_date THEN NULL
                 WHEN {cutover} IS NULL OR n0.as_of_date >= {cutover} THEN
                      CASE WHEN n0.vendor_forward IS NOT NULL THEN 'vendor' END
                 WHEN f.parity_forward IS NOT NULL THEN 'parity'
                 WHEN n0.vendor_forward IS NOT NULL THEN 'vendor_single_price' END AS forward_source
        FROM n0 LEFT JOIN fits f USING (as_of_date, root, expiration)""")
    con.execute("DROP TABLE n0")


def _fit_parity(con: duckdb.DuckDBPyConnection, strikes: int) -> None:
    """Fit one forward per (date, root, expiration) from put-call parity on the strikes nearest the money (DATA-14).

    At each strike with a valid call and put quote and both bids above zero, the mids satisfy
    ``C − P = D·(F − K)``. Over the ``strikes`` strikes with the smallest ``|C − P|``, a least-squares
    line ``C − P = a + b·K`` gives ``D = −b`` and ``F = a / D``. A fit is valid when it uses at least two
    strikes, ``C − P`` changes sign across them, and ``0 < D ≤ 1.05``; otherwise ``parity_forward`` and
    ``parity_discount`` are null (``parity_strikes`` still records the strikes used).

    :param con: The working database, with table ``n0``.
    :param strikes: How many strikes nearest the money to use.
    """
    con.execute(f"""
        CREATE TABLE fits AS
        WITH pairs AS (
            SELECT c.as_of_date, c.root, c.expiration, c.strike, (c.bid + c.ask) / 2 - (q.bid + q.ask) / 2 AS diff
            FROM n0 c JOIN n0 q USING (as_of_date, root, expiration, strike)
            WHERE c.option_type = 'call' AND q.option_type = 'put' AND c.as_of_date < c.settlement_date
              AND c.bid > 0 AND c.ask >= c.bid AND q.bid > 0 AND q.ask >= q.bid),
        ranked AS (SELECT *, row_number() OVER (PARTITION BY as_of_date, root, expiration ORDER BY abs(diff), strike) AS rn
                   FROM pairs),
        g AS (SELECT as_of_date, root, expiration, CAST(count(*) AS INTEGER) AS parity_strikes,
                     -regr_slope(diff, strike) AS d, regr_intercept(diff, strike) AS a, min(diff) AS lo, max(diff) AS hi
              FROM ranked WHERE rn <= {int(strikes)} GROUP BY ALL)
        SELECT as_of_date, root, expiration, parity_strikes,
               CASE WHEN ok THEN a / d END AS parity_forward, CASE WHEN ok THEN d END AS parity_discount
        FROM (SELECT *, parity_strikes >= 2 AND lo < 0 AND hi > 0 AND d > 0 AND d <= {PARITY_MAX_DISCOUNT} AS ok FROM g)""")


def partitions(con: duckdb.DuckDBPyConnection) -> list[tuple[int, int]]:
    """The (year, month) partitions of table ``n``, in order.

    :param con: The working database.
    :returns: The partitions.
    """
    return con.execute("SELECT DISTINCT year(as_of_date), month(as_of_date) FROM n ORDER BY 1, 2").fetchall()


def read_partition(con: duckdb.DuckDBPyConnection, year: int, month: int, import_id: str,
                   internal_greeks_from: date | None) -> pa.Table:
    """One month of normalized rows, with internal greeks, in the market schema and storage order.

    :param con: The working database, with table ``n``.
    :param year: The partition's year.
    :param month: The partition's month.
    :param import_id: The import, written into every row.
    :param internal_greeks_from: From this date the vendor's greeks are copied; before it they are
        recomputed (``None``: always copied).
    :returns: The rows, sorted by as-of time, root, expiration, type and strike.
    """
    cutover = _sql_date(internal_greeks_from)
    copied = f"({cutover} IS NULL OR as_of_date >= {cutover})"
    table = con.sql(f"""
        SELECT * EXCLUDE (iv_raw, fwd_raw, file),
            CASE WHEN {copied} AND iv IS NOT NULL THEN vendor_delta END AS delta,
            CASE WHEN {copied} AND iv IS NOT NULL THEN vendor_gamma END AS gamma,
            CASE WHEN {copied} AND iv IS NOT NULL THEN vendor_vega END AS vega,
            CASE WHEN {copied} AND iv IS NOT NULL THEN vendor_theta END AS theta,
            CASE WHEN {copied} THEN '{GreeksSource.VENDOR}' ELSE '{GreeksSource.RECOMPUTED}' END AS greeks_source,
            '{import_id}' AS import_id
        FROM n WHERE year(as_of_date) = {int(year)} AND month(as_of_date) = {int(month)}
        ORDER BY as_of, root, expiration, option_type, strike""").to_arrow_table()
    table = _recompute_greeks(table)
    return table.select(list(MARKET_COLUMNS)).cast(MARKET_SCHEMA)


def _recompute_greeks(table: pa.Table) -> pa.Table:
    """Fill the internal greeks of rows marked ``recomputed`` with Black-76 (CONV-10, DATA-15).

    Rows without a positive time to expiry, IV and forward keep null greeks.

    :param table: Rows with ``greeks_source``, ``time_to_expiry_years``, ``forward``, ``iv``, ``strike``,
        ``option_type`` and the four greek columns.
    :returns: The table with the recomputed greeks filled in.
    """
    recompute = pc.equal(table["greeks_source"], GreeksSource.RECOMPUTED.value).to_numpy(zero_copy_only=False)
    if not recompute.any():
        return table

    def col(name: str) -> np.ndarray:
        """A column as a float array with NaN for nulls.

        :param name: The column.
        """
        return pc.cast(table[name], pa.float64()).to_numpy(zero_copy_only=False).astype(float)

    t, f, v, k = col("time_to_expiry_years"), col("forward"), col("iv"), col("strike")
    ok = recompute & (t > 0) & (f > 0) & (v > 0) & np.isfinite(t + f + v + k)
    is_call = pc.equal(table["option_type"], "call").to_numpy(zero_copy_only=False)
    result = {name: col(name) for name in ("delta", "gamma", "vega", "theta")}
    if ok.any():
        g = black76.greeks(f[ok], k[ok], t[ok], v[ok], is_call[ok])
        for name in result:
            result[name][ok] = getattr(g, name)
    for name, values in result.items():
        values[recompute & ~ok] = np.nan
        array = pa.array(values, mask=np.isnan(values), type=pa.float64())
        table = table.set_column(table.schema.get_field_index(name), name, array)
    return table

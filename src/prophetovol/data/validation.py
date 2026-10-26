"""Validation of an import (DATA-20): every check as one SQL aggregate per date, with examples.

Checks run in two stages inside the ingest's working database:

* **before derivation**, on the parsed rows (table ``p``): the structural errors that make derivation
  impossible or meaningless (unparseable values, several underlyings, unknown roots, non-European style,
  duplicate contracts), plus the information-only repeated vendor symbols;
* **after derivation**, on the normalized rows (table ``n``): the warnings about quotes, IV, forwards
  and dates, which need settlement dates and forwards to judge.
"""

from __future__ import annotations

import statistics
from datetime import date

import duckdb

from prophetovol.data.ivolatility import COLUMNS
from prophetovol.data.quality import DateCount, QualityCheck, Severity

EXAMPLES = 5
"""Example rows kept per check."""

LOW_CONTRACT_RATIO = 0.5
"""A date is flagged when its contracts fall below this share of the median of the 5 surrounding dates."""

_P_EXAMPLE = ("file", "date_raw AS date", "vendor_symbol AS option_symbol", "ex_raw AS expiration",
              "strike_raw AS strike", "cp AS call_put", "style", "bid_raw AS bid", "ask_raw AS ask")
_N_EXAMPLE = ("file", "as_of_date", "vendor_symbol AS option_symbol", "expiration", "strike", "option_type",
              "bid", "ask", "iv_raw AS iv", "fwd_raw AS stock_price_for_iv")


def _check(con: duckdb.DuckDBPyConnection, name: str, severity: Severity, description: str, table: str,
           condition: str, date_column: str, example_columns: tuple[str, ...]) -> QualityCheck:
    """Run one row-level check: count per date, and keep examples.

    :param con: The working database.
    :param name: The check's id.
    :param severity: Its severity.
    :param description: What it looks for.
    :param table: The table to check (``p`` or ``n``).
    :param condition: A SQL condition true for flagged rows.
    :param date_column: The snapshot-date column of the table.
    :param example_columns: Column expressions for the example rows.
    :returns: The check's findings.
    """
    by_date = con.execute(f"SELECT {date_column}, count(*) FROM {table} WHERE {condition} GROUP BY 1 ORDER BY 1 NULLS FIRST").fetchall()
    total = sum(n for _, n in by_date)
    examples = []
    if total:
        cur = con.execute(f"SELECT {', '.join(example_columns)} FROM {table} WHERE {condition} LIMIT {EXAMPLES}")
        names = [c[0] for c in cur.description]
        examples = [_jsonable(dict(zip(names, row))) for row in cur.fetchall()]
    return QualityCheck(name=name, severity=severity, description=description, count=total,
                        by_date=[DateCount(as_of_date=d, count=n) for d, n in by_date], examples=examples)


def _jsonable(row: dict) -> dict:
    """Make an example row JSON-friendly (dates as ISO text).

    :param row: The row.
    :returns: The same row with dates converted.
    """
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}


def header_check(headers: dict[str, tuple[str, ...]]) -> QualityCheck:
    """Check every file's header against the 22 vendor columns (DATA-1).

    :param headers: Each file's name and header row.
    :returns: The findings (one per file whose header differs).
    """
    bad = {name: h for name, h in headers.items() if tuple(h) != COLUMNS}
    examples = [{"file": name, "missing": [c for c in COLUMNS if c not in h], "unexpected": [c for c in h if c not in COLUMNS],
                 "in_order": tuple(h) == COLUMNS} for name, h in list(bad.items())[:EXAMPLES]]
    return QualityCheck(name="header", severity=Severity.ERROR,
                        description="Required columns missing, misnamed or out of order (DATA-1).",
                        count=len(bad), examples=examples)


def structural_checks(con: duckdb.DuckDBPyConnection, known_underlyings: set[str],
                      file_duplicates: dict[str, list[str]]) -> list[QualityCheck]:
    """The checks on parsed rows (table ``p``, with the ``roots`` table loaded).

    :param con: The working database.
    :param known_underlyings: The configured underlyings.
    :param file_duplicates: For each file name, the ids of existing imports with the same file hash (DATA-12).
    :returns: The findings, in check order.
    """
    checks = [
        _check(con, "unparseable_value", Severity.ERROR,
               "A required field (date, expiration, strike, call/put, bid, ask) could not be parsed.", "p",
               "dt IS NULL OR ex IS NULL OR strike IS NULL OR bid IS NULL OR ask IS NULL OR coalesce(cp, '') NOT IN ('C', 'P')",
               "dt", _P_EXAMPLE),
    ]
    symbols = con.execute("SELECT symbol, count(*) FROM p GROUP BY 1 ORDER BY 2 DESC").fetchall()
    checks.append(QualityCheck(
        name="several_underlyings", severity=Severity.ERROR,
        description="The import's files contain more than one underlying (DATA-3).",
        count=len(symbols) - 1 if len(symbols) > 1 else 0,
        examples=[{"symbol": s, "rows": n} for s, n in symbols[:EXAMPLES]] if len(symbols) > 1 else []))
    unknown = [s for s, _ in symbols if s not in known_underlyings]
    checks.append(QualityCheck(
        name="unknown_underlying", severity=Severity.ERROR,
        description="The underlying is not configured (REF-1).",
        count=sum(n for s, n in symbols if s in unknown), examples=[{"symbol": s} for s in unknown[:EXAMPLES]]))
    checks += [
        _check(con, "unknown_root", Severity.ERROR, "The option root is not configured for the underlying (REF-1).", "p",
               "vendor_root NOT IN (SELECT vendor_root FROM roots)", "dt", _P_EXAMPLE),
        _check(con, "not_european", Severity.ERROR, "Style other than E: Phase 1 supports European options only.", "p",
               "coalesce(style, '') <> 'E'", "dt", _P_EXAMPLE),
    ]
    dup = con.execute("""
        SELECT p.dt, count(*) FROM p JOIN roots r USING (vendor_root)
        WHERE (p.dt, r.root, p.ex, p.strike, p.cp) IN (
            SELECT (p2.dt, r2.root, p2.ex, p2.strike, p2.cp) FROM p p2 JOIN roots r2 USING (vendor_root)
            GROUP BY 1 HAVING count(*) > 1)
        GROUP BY 1 ORDER BY 1""").fetchall()
    dup_examples = con.execute("""
        SELECT p2.date_raw AS date, r2.root, p2.ex_raw AS expiration, p2.strike_raw AS strike, p2.cp AS call_put, count(*) AS rows
        FROM p p2 JOIN roots r2 USING (vendor_root) GROUP BY ALL HAVING count(*) > 1 LIMIT 5""")
    names = [c[0] for c in dup_examples.description]
    checks.append(QualityCheck(
        name="duplicate_contract", severity=Severity.ERROR,
        description="The same contract (date, root, expiration, strike, call/put) appears more than once.",
        count=sum(n for _, n in dup), by_date=[DateCount(as_of_date=d, count=n) for d, n in dup],
        examples=[dict(zip(names, r)) for r in dup_examples.fetchall()]))
    repeated = con.execute("""
        SELECT dt, count(*) FROM (SELECT dt, vendor_symbol FROM p GROUP BY 1, 2
                                  HAVING count(DISTINCT (ex, strike, cp)) > 1) GROUP BY 1 ORDER BY 1""").fetchall()
    rep_examples = con.execute("""
        SELECT date_raw AS date, vendor_symbol AS option_symbol, list(DISTINCT ex_raw || ' ' || strike_raw || ' ' || cp) AS contracts
        FROM p GROUP BY date_raw, vendor_symbol HAVING count(DISTINCT (ex, strike, cp)) > 1 LIMIT 5""")
    names = [c[0] for c in rep_examples.description]
    checks.append(QualityCheck(
        name="repeated_vendor_symbol", severity=Severity.INFO,
        description="The same vendor option symbol names different contracts on one date (older five-character codes).",
        count=sum(n for _, n in repeated), by_date=[DateCount(as_of_date=d, count=n) for d, n in repeated],
        examples=[dict(zip(names, r)) for r in rep_examples.fetchall()]))
    dupes = {f: ids for f, ids in file_duplicates.items() if ids}
    checks.append(QualityCheck(
        name="file_already_imported", severity=Severity.INFO,
        description="A file with the same contents is part of an existing import (DATA-12); the import can be cancelled at commit.",
        count=len(dupes), examples=[{"file": f, "imports": ids} for f, ids in list(dupes.items())[:EXAMPLES]]))
    return [c for c in checks if c.count]


def content_checks(con: duckdb.DuckDBPyConnection, sessions: set[date]) -> list[QualityCheck]:
    """The checks on normalized rows (table ``n``, with forwards decided in column ``forward_source``).

    :param con: The working database.
    :param sessions: The trading days from the calendar, covering the import's date range.
    :returns: The findings, in check order.
    """
    checks = [
        _check(con, "crossed_quote", Severity.WARNING, "Bid above ask.", "n", "bid > ask", "as_of_date", _N_EXAMPLE),
        _check(con, "zero_ask", Severity.WARNING, "Zero ask (or zero bid and ask).", "n", "ask = 0", "as_of_date", _N_EXAMPLE),
        _check(con, "iv_minus_one_before_settlement", Severity.WARNING,
               "IV of -1 on a date before the contract's settlement date.", "n",
               "iv_raw = -1 AND as_of_date < settlement_date", "as_of_date", _N_EXAMPLE),
        _check(con, "missing_vendor_forward", Severity.WARNING, "Missing or non-positive stock price for iv.", "n",
               "fwd_raw IS NULL OR fwd_raw <= 0", "as_of_date", _N_EXAMPLE),
    ]
    no_fit = con.execute("""
        SELECT as_of_date, count(DISTINCT (root, expiration)) FROM n WHERE forward_source = 'vendor_single_price'
        GROUP BY 1 ORDER BY 1""").fetchall()
    checks.append(QualityCheck(
        name="no_parity_forward", severity=Severity.WARNING,
        description="No valid parity forward where one is needed; the vendor's single price is used (DATA-14). "
                    "Counted per expiration.",
        count=sum(n for _, n in no_fit), by_date=[DateCount(as_of_date=d, count=n) for d, n in no_fit],
        examples=[{"as_of_date": d.isoformat(), "expirations": n} for d, n in no_fit[:EXAMPLES]]))
    counts = con.execute("SELECT as_of_date, count(*) FROM n GROUP BY 1 ORDER BY 1").fetchall()
    dates = [d for d, _ in counts]
    if dates:
        in_range = {s for s in sessions if dates[0] <= s <= dates[-1]}
        missing = sorted(in_range - set(dates))
        checks.append(QualityCheck(
            name="missing_trading_day", severity=Severity.WARNING,
            description="A trading day in the import's date range is missing from the files.", count=len(missing),
            by_date=[DateCount(as_of_date=d, count=1) for d in missing],
            examples=[{"as_of_date": d.isoformat()} for d in missing[:EXAMPLES]]))
        extra = sorted(set(dates) - sessions)
        checks.append(QualityCheck(
            name="not_a_trading_day", severity=Severity.WARNING,
            description="A date in the files is not a trading day (a weekend or holiday).", count=len(extra),
            by_date=[DateCount(as_of_date=d, count=1) for d in extra],
            examples=[{"as_of_date": d.isoformat()} for d in extra[:EXAMPLES]]))
        low = []
        for i, (d, n) in enumerate(counts):
            window = [m for _, m in counts[max(0, i - 2): i + 3]]
            if len(window) >= 3 and n < LOW_CONTRACT_RATIO * statistics.median(window):
                low.append((d, n, statistics.median(window)))
        checks.append(QualityCheck(
            name="low_contract_count", severity=Severity.WARNING,
            description=f"Contracts on a date below {LOW_CONTRACT_RATIO:.0%} of the median of the 5 surrounding dates.",
            count=len(low), by_date=[DateCount(as_of_date=d, count=1) for d, _, _ in low],
            examples=[{"as_of_date": d.isoformat(), "contracts": n, "median_nearby": m} for d, n, m in low[:EXAMPLES]]))
    checks.append(_check(con, "vendor_flagged", Severity.INFO, "Rows with the vendor's * flag (meaning unconfirmed).",
                         "n", "vendor_flag", "as_of_date", _N_EXAMPLE))
    return [c for c in checks if c.count]

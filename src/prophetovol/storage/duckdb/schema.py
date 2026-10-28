"""Database schemas and their migrations (§4.2 of the implementation plan).

Each database has a ``schema_version`` table. Opening a home directory applies, in order and each
in its own transaction, every migration newer than the database's version. Later phases append
migrations; existing ones are never edited.

Every instant is stored as a ``TIMESTAMP`` holding UTC, and JSON as text, so the schema stays
portable and reading needs no time-zone settings.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from prophetovol.core.errors import ConfigurationError
from prophetovol.core.ids import utc_now


@dataclass(frozen=True)
class Migration:
    """One schema change.

    :param version: The schema version it produces, from 1, one more than the previous migration.
    :param description: What it changes, for people.
    :param statements: The SQL statements, run in order in one transaction.
    """

    version: int
    description: str
    statements: tuple[str, ...]


CATALOG_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "M1 catalog: versioned definitions, imports and their files, data versions, jobs, attempts", (
        """CREATE TABLE definitions (
            kind VARCHAR NOT NULL, key VARCHAR NOT NULL, version INTEGER NOT NULL,
            body VARCHAR NOT NULL, content_hash VARCHAR NOT NULL,
            actor VARCHAR NOT NULL, channel VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
            PRIMARY KEY (kind, key, version))""",
        """CREATE TABLE imports (
            import_id VARCHAR PRIMARY KEY, underlying VARCHAR NOT NULL, data_source VARCHAR NOT NULL,
            status VARCHAR NOT NULL, rows BIGINT, first_as_of_date DATE, last_as_of_date DATE,
            quality_report VARCHAR, commit_choice VARCHAR, error VARCHAR,
            actor VARCHAR NOT NULL, channel VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL, committed_at TIMESTAMP)""",
        """CREATE TABLE import_files (
            import_id VARCHAR NOT NULL, position INTEGER NOT NULL, name VARCHAR NOT NULL,
            size_bytes BIGINT NOT NULL, sha256 VARCHAR NOT NULL,
            PRIMARY KEY (import_id, position))""",
        """CREATE TABLE data_versions (
            underlying VARCHAR NOT NULL, as_of TIMESTAMP NOT NULL, as_of_date DATE NOT NULL,
            import_id VARCHAR NOT NULL, state VARCHAR NOT NULL, contracts INTEGER NOT NULL,
            quality_flags VARCHAR NOT NULL, state_changed_at TIMESTAMP NOT NULL,
            PRIMARY KEY (underlying, as_of, import_id))""",
        """CREATE TABLE jobs (
            job_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, params VARCHAR NOT NULL, status VARCHAR NOT NULL,
            progress_done BIGINT, progress_total BIGINT, progress_label VARCHAR NOT NULL,
            result VARCHAR, error VARCHAR, cancel_requested BOOLEAN NOT NULL,
            actor VARCHAR NOT NULL, channel VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL, started_at TIMESTAMP, finished_at TIMESTAMP)""",
        """CREATE TABLE attempts (
            attempt_id VARCHAR PRIMARY KEY, operation VARCHAR NOT NULL, params_summary VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL, reasons VARCHAR NOT NULL,
            actor VARCHAR NOT NULL, channel VARCHAR NOT NULL, attempted_at TIMESTAMP NOT NULL)""",
    )),
    Migration(2, "Data lifecycle: run provenance, invalidations and file-operation recovery", (
        """CREATE TABLE runs (
            run_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL,
            data_superseded BOOLEAN NOT NULL DEFAULT FALSE)""",
        """CREATE TABLE run_data_versions (
            run_id VARCHAR NOT NULL, underlying VARCHAR NOT NULL, as_of TIMESTAMP NOT NULL,
            import_id VARCHAR NOT NULL, PRIMARY KEY (run_id, underlying, as_of, import_id))""",
        """CREATE TABLE run_invalidations (
            run_id VARCHAR NOT NULL, underlying VARCHAR NOT NULL, as_of TIMESTAMP NOT NULL,
            import_id VARCHAR NOT NULL, as_of_date DATE NOT NULL,
            PRIMARY KEY (run_id, underlying, as_of, import_id))""",
        "CREATE TABLE file_operations (operation_id VARCHAR PRIMARY KEY)",
    )),
    Migration(3, "Runs: provenance, status and the registry versions used (RUN-20 to RUN-30)", tuple(
        f"ALTER TABLE runs ADD COLUMN {column}" for column in (
            "spec_id VARCHAR", "spec_version INTEGER", "spec_hash VARCHAR", "stress_refs VARCHAR",
            "config VARCHAR", "config_hash VARCHAR", "underlying VARCHAR", "underlying_version INTEGER",
            "data_source VARCHAR", "data_source_version INTEGER", "calendar_version VARCHAR",
            "software_versions VARCHAR", "job_id VARCHAR", "steps_total INTEGER", "steps_completed INTEGER",
            "last_as_of TIMESTAMP", "partial BOOLEAN", "error VARCHAR", "final_pnl DOUBLE", "final_equity DOUBLE",
            "label VARCHAR", "actor VARCHAR", "channel VARCHAR", "created_at TIMESTAMP", "started_at TIMESTAMP",
            "finished_at TIMESTAMP")) + (
        """CREATE TABLE run_registry_versions (
            run_id VARCHAR NOT NULL, kind VARCHAR NOT NULL, name VARCHAR NOT NULL, version VARCHAR NOT NULL,
            PRIMARY KEY (run_id, kind, name))""",
    )),
)
"""Migrations of ``catalog.duckdb``."""

RESULTS_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "results database created; run output tables arrive with Phase 14", ()),
    Migration(2, "Run output: snapshots, trades, structures, events (RES-1 to RES-20)", (
        """CREATE TABLE position_snapshots (
            run_id VARCHAR, step BIGINT, as_of TIMESTAMP, structure_id VARCHAR, leg_id VARCHAR, position_key VARCHAR,
            osi_symbol VARCHAR, root VARCHAR, vendor_symbol VARCHAR, vendor_root VARCHAR, settlement_style VARCHAR,
            expiration DATE, settlement_date DATE, last_trading_date DATE, expiry_timestamp TIMESTAMP, strike DOUBLE,
            option_type VARCHAR, quantity DOUBLE, time_to_expiry_years DOUBLE, days_to_expiry DOUBLE,
            trading_days_to_expiry BIGINT, mark DOUBLE, mark_source VARCHAR, bid DOUBLE, ask DOUBLE, iv DOUBLE,
            index_level DOUBLE, forward DOUBLE, forward_source VARCHAR, market_value DOUBLE, cash_flow DOUBLE,
            fees DOUBLE, period_pnl DOUBLE, cumulative_pnl DOUBLE, delta DOUBLE, gamma DOUBLE, vega DOUBLE,
            theta DOUBLE, dollar_delta DOUBLE, dollar_gamma_1pct DOUBLE, dollar_vega DOUBLE, dollar_theta DOUBLE,
            flags VARCHAR[])""",
        """CREATE TABLE portfolio_snapshots (
            run_id VARCHAR, step BIGINT, as_of TIMESTAMP, index_level DOUBLE, market_value DOUBLE, cash_flow DOUBLE,
            fees DOUBLE, period_pnl DOUBLE, cumulative_pnl DOUBLE, equity DOUBLE, period_return DOUBLE,
            dollar_delta DOUBLE, dollar_gamma_1pct DOUBLE, dollar_vega DOUBLE, dollar_theta DOUBLE,
            open_structures BIGINT, contracts_held DOUBLE, worst_stress_loss DOUBLE, flags VARCHAR[],
            PRIMARY KEY (run_id, step))""",
        """CREATE TABLE trades (
            run_id VARCHAR, trade_id VARCHAR, step BIGINT, as_of TIMESTAMP, structure_id VARCHAR, leg_id VARCHAR,
            position_key VARCHAR, osi_symbol VARCHAR, action VARCHAR, quantity DOUBLE, price DOUBLE, fees DOUBLE,
            cash_flow DOUBLE, reason VARCHAR, forced BOOLEAN, PRIMARY KEY (run_id, trade_id))""",
        """CREATE TABLE structures (
            run_id VARCHAR, structure_id VARCHAR, parent_id VARCHAR, units DOUBLE, opened_step BIGINT,
            opened_as_of TIMESTAMP, closed_step BIGINT, closed_as_of TIMESTAMP, status VARCHAR, cumulative_pnl DOUBLE,
            PRIMARY KEY (run_id, structure_id))""",
        """CREATE TABLE events (
            run_id VARCHAR, seq BIGINT, step BIGINT, as_of TIMESTAMP, type VARCHAR, level VARCHAR,
            structure_id VARCHAR, message VARCHAR, details VARCHAR, PRIMARY KEY (run_id, seq))""",
        # Structure snapshots are a view over the position snapshots (RES-11).
        """CREATE VIEW structure_snapshots AS
            SELECT run_id, step, min(as_of) AS as_of, structure_id,
                   sum(market_value) AS market_value, sum(cash_flow) AS cash_flow, sum(fees) AS fees,
                   sum(period_pnl) AS period_pnl,
                   sum(sum(period_pnl)) OVER (PARTITION BY run_id, structure_id ORDER BY step) AS cumulative_pnl,
                   sum(coalesce(dollar_delta, 0)) AS dollar_delta,
                   sum(coalesce(dollar_gamma_1pct, 0)) AS dollar_gamma_1pct,
                   sum(coalesce(dollar_vega, 0)) AS dollar_vega, sum(coalesce(dollar_theta, 0)) AS dollar_theta,
                   count(*) FILTER (WHERE leg_id <> 'hedge' AND quantity <> 0) AS legs_held
            FROM position_snapshots GROUP BY run_id, step, structure_id""",
    )),
)
"""Migrations of ``results.duckdb``."""


def schema_version(con: duckdb.DuckDBPyConnection) -> int:
    """The database's schema version: 0 for a new, empty database.

    :param con: A connection to the database.
    :returns: The highest applied migration's version.
    """
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'schema_version'").fetchall()[0][0]
    if not exists:
        return 0
    return con.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchall()[0][0]


def apply_migrations(con: duckdb.DuckDBPyConnection, migrations: tuple[Migration, ...]) -> int:
    """Bring a database up to the newest migration.

    :param con: A read-write connection to the database.
    :param migrations: Its migrations, in version order.
    :returns: The schema version after migrating.
    :raises ConfigurationError: If the migrations are not numbered 1, 2, 3, …, or the database was
        created by a newer version of ProphetoVol.
    """
    if [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
        raise ConfigurationError("migrations must be numbered 1, 2, 3, … in order")
    con.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY, description VARCHAR NOT NULL, applied_at TIMESTAMP NOT NULL)""")
    current = schema_version(con)
    if current > len(migrations):
        raise ConfigurationError(
            f"this database is at schema version {current}, newer than this ProphetoVol supports "
            f"({len(migrations)}): upgrade ProphetoVol")
    for migration in migrations[current:]:
        con.execute("BEGIN TRANSACTION")
        try:
            for statement in migration.statements:
                con.execute(statement)
            con.execute("INSERT INTO schema_version VALUES (?, ?, ?)",
                        [migration.version, migration.description, utc_now().replace(tzinfo=None)])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return schema_version(con)

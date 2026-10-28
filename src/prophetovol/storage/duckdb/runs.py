"""Runs in the catalog and their output in ``results.duckdb`` (RUN-20 to RUN-40, RES-1 to RES-20).

Mixed into :class:`~prophetovol.storage.duckdb.adapter.DuckDBAdapter`. A run's row records its
provenance (RUN-30); ``run_data_versions`` the data versions it reads, which invalidation follows
(RUN-40); ``run_registry_versions`` the implementation versions it uses. Its output is written in one
transaction of the results database (RUN-23). Instants are stored as naive UTC and returned aware.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from prophetovol.core.errors import ImmutableEntityError, NotFoundError
from prophetovol.core.paging import Page, check_page
from prophetovol.core.records import DataVersionRecord, RunRecord, RunStatus

RESULT_TABLES: tuple[str, ...] = ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events")
"""The run output tables, in write order."""

_ORDERS: dict[str, list[str]] = {
    "position_snapshots": ["step", "structure_seq", "structure_id", "position_key"],
    "portfolio_snapshots": ["step"],
    "trades": ["step", "trade_seq"],
    "structures": ["opened_step", "structure_seq"],
    "events": ["seq"],
    "structure_snapshots": ["step", "structure_seq"],
}


def _naive(value: datetime | None) -> datetime | None:
    """An aware instant as the naive UTC value stored.

    :param value: The instant, or None.
    :returns: Naive UTC, or None.
    """
    return None if value is None else value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    """A stored naive UTC value as an aware instant.

    :param value: The value, or None.
    :returns: Aware UTC, or None.
    """
    return None if value is None else value.replace(tzinfo=timezone.utc)


def _without_zone(table: pa.Table) -> pa.Table:
    """Convert a table's aware timestamp columns to naive UTC for storage.

    :param table: The table.
    :returns: The table with naive timestamps.
    """
    for i, f in enumerate(table.schema):
        if pa.types.is_timestamp(f.type) and f.type.tz is not None:
            table = table.set_column(i, f.name, table.column(i).cast(pa.timestamp("us")))
    return table


def _with_zone(table: pa.Table) -> pa.Table:
    """Mark a table's naive timestamp columns as UTC.

    :param table: The table read.
    :returns: The table with aware timestamps.
    """
    for i, f in enumerate(table.schema):
        if pa.types.is_timestamp(f.type) and f.type.tz is None:
            table = table.set_column(i, f.name, table.column(i).cast(pa.timestamp("us", tz="UTC")))
    return table


class _RunStorage:
    """Run storage mixed into the DuckDB adapter."""

    def create_run(self, record: RunRecord, data_versions: list[DataVersionRecord]) -> None:
        """Record a new run with the data versions it will read and the registry versions it uses, atomically.

        :param record: The run, in status ``queued``.
        :param data_versions: The data version each step reads (decision 30).
        """
        r = record
        self._cat.execute("BEGIN TRANSACTION")
        try:
            self._cat.execute(
                """INSERT INTO runs (run_id, status, data_superseded, spec_id, spec_version, spec_hash, stress_refs,
                    config, config_hash, underlying, underlying_version, data_source, data_source_version,
                    calendar_version, software_versions, job_id, steps_total, steps_completed, last_as_of, partial,
                    error, final_pnl, final_equity, label, actor, channel, created_at, started_at, finished_at)
                   VALUES (?, ?, FALSE, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [r.run_id, r.status.value, r.spec_id, r.spec_version, r.spec_hash, json.dumps(r.stress_refs),
                 json.dumps(r.config, sort_keys=True), r.config_hash, r.underlying, r.underlying_version,
                 r.data_source, r.data_source_version, r.calendar_version, json.dumps(r.software_versions),
                 r.job_id, r.steps_total, r.steps_completed, _naive(r.last_as_of), r.partial, r.error, r.final_pnl,
                 r.final_equity, r.label, r.actor, str(r.channel), _naive(r.created_at), _naive(r.started_at),
                 _naive(r.finished_at)])
            if data_versions:
                self._cat.executemany("INSERT INTO run_data_versions VALUES (?, ?, ?, ?)",
                                      [[r.run_id, v.underlying, _naive(v.as_of), v.import_id] for v in data_versions])
            for key, version in sorted(r.registry_versions.items()):
                kind, name = key.split("/", 1)
                self._cat.execute("INSERT INTO run_registry_versions VALUES (?, ?, ?, ?)", [r.run_id, kind, name, version])
            self._cat.execute("COMMIT")
        except Exception:
            self._cat.execute("ROLLBACK")
            raise

    def update_run(self, record: RunRecord) -> None:
        """Store a run's status, progress, outcome and times.

        :param record: The run.
        :raises NotFoundError: If it does not exist.
        """
        r = record
        self.get_run(r.run_id)
        self._cat.execute(
            """UPDATE runs SET status = ?, job_id = ?, steps_completed = ?, last_as_of = ?, partial = ?, error = ?,
                final_pnl = ?, final_equity = ?, started_at = ?, finished_at = ? WHERE run_id = ?""",
            [r.status.value, r.job_id, r.steps_completed, _naive(r.last_as_of), r.partial, r.error, r.final_pnl,
             r.final_equity, _naive(r.started_at), _naive(r.finished_at), r.run_id])

    def _run(self, row: dict[str, Any], registry: dict[str, str]) -> RunRecord:
        """Build a run record from its catalog row.

        :param row: The row.
        :param registry: Its registry versions, keyed kind/name.
        :returns: The record.
        """
        return RunRecord(
            run_id=row["run_id"], status=row["status"], spec_id=row["spec_id"], spec_version=row["spec_version"],
            spec_hash=row["spec_hash"], stress_refs=json.loads(row["stress_refs"] or "[]"),
            config=json.loads(row["config"]), config_hash=row["config_hash"], underlying=row["underlying"],
            underlying_version=row["underlying_version"], data_source=row["data_source"],
            data_source_version=row["data_source_version"], calendar_version=row["calendar_version"],
            software_versions=json.loads(row["software_versions"]), registry_versions=registry,
            job_id=row["job_id"], steps_total=row["steps_total"], steps_completed=row["steps_completed"] or 0,
            last_as_of=_aware(row["last_as_of"]), partial=bool(row["partial"]), error=row["error"],
            data_superseded=bool(row["data_superseded"]), final_pnl=row["final_pnl"],
            final_equity=row["final_equity"], label=row["label"] or "", actor=row["actor"], channel=row["channel"],
            created_at=_aware(row["created_at"]), started_at=_aware(row["started_at"]),
            finished_at=_aware(row["finished_at"]))

    def _registry_versions(self, run_ids: list[str]) -> dict[str, dict[str, str]]:
        """The registry versions of some runs.

        :param run_ids: The runs.
        :returns: Versions keyed kind/name, by run.
        """
        out: dict[str, dict[str, str]] = {i: {} for i in run_ids}
        if not run_ids:
            return out
        t = self._ibis.table("run_registry_versions")
        for r in self._rows(t.filter(t.run_id.isin(run_ids)).order_by(["run_id", "kind", "name"])):
            out[r["run_id"]][f"{r['kind']}/{r['name']}"] = r["version"]
        return out

    def get_run(self, run_id: str) -> RunRecord:
        """A run, with its registry versions and its data-superseded flag.

        :param run_id: The run.
        :returns: The record.
        :raises NotFoundError: If it does not exist.
        """
        t = self._ibis.table("runs")
        rows = self._rows(t.filter((t.run_id == run_id) & t.spec_id.notnull()))
        if not rows:
            raise NotFoundError(f"no run {run_id!r}")
        return self._run(rows[0], self._registry_versions([run_id])[run_id])

    def page_runs(self, offset: int = 0, limit: int = 50, statuses: list[RunStatus] | None = None) -> Page[RunRecord]:
        """Runs, newest first.

        :param offset: Index of the first run.
        :param limit: Page size.
        :param statuses: Only these statuses, when given.
        :returns: The page.
        """
        check_page(offset, limit)
        t = self._ibis.table("runs")
        t = t.filter(t.spec_id.notnull())
        if statuses:
            t = t.filter(t.status.isin([RunStatus(s).value for s in statuses]))
        total = t.count().to_pyarrow().as_py()
        rows = self._rows(t.order_by([t.created_at.desc(), t.run_id]).limit(limit, offset=offset))
        registry = self._registry_versions([r["run_id"] for r in rows])
        return Page(items=[self._run(r, registry[r["run_id"]]) for r in rows], total=total, offset=offset, limit=limit)

    def run_data_versions(self, run_id: str) -> list[DataVersionRecord]:
        """The data versions a run reads, in as-of order, in their current state.

        :param run_id: The run.
        :returns: The versions.
        """
        links = self._ibis.table("run_data_versions")
        links = links.filter(links.run_id == run_id).select("underlying", "as_of", "import_id")
        versions = self._ibis.table("data_versions")
        expr = versions.semi_join(links, ["underlying", "as_of", "import_id"]).order_by(["as_of", "import_id"])
        return [DataVersionRecord(underlying=r["underlying"], as_of=_aware(r["as_of"]), as_of_date=r["as_of_date"],
                                  import_id=r["import_id"], state=r["state"], contracts=r["contracts"],
                                  quality_flags=json.loads(r["quality_flags"] or "[]"),
                                  state_changed_at=_aware(r["state_changed_at"]))
                for r in self._rows(expr)]

    def write_run_results(self, run_id: str, tables: dict[str, pa.Table]) -> None:
        """Store a run's output in one transaction (RUN-23): all of it or nothing.

        :param run_id: The run.
        :param tables: Tables by name, in their record models' schemas.
        :raises ImmutableEntityError: If the run already has results.
        """
        if any(self.count_run_results(run_id, name) for name in RESULT_TABLES):
            raise ImmutableEntityError(f"run {run_id} already has stored results")
        self._res.execute("BEGIN TRANSACTION")
        try:
            for name in RESULT_TABLES:
                table = _without_zone(tables[name])
                if table.num_rows == 0:
                    continue
                columns = ", ".join(table.column_names)
                self._res.register("_incoming", table)
                try:
                    self._res.execute(f"INSERT INTO {name} ({columns}) SELECT {columns} FROM _incoming")
                finally:
                    self._res.unregister("_incoming")
            self._res.execute("COMMIT")
        except Exception:
            self._res.execute("ROLLBACK")
            raise

    def _results_expr(self, run_id: str, table: str):
        """An Ibis expression over one run's rows of an output table or view, with its ordering helpers.

        :param run_id: The run.
        :param table: The table or view.
        :returns: The filtered expression.
        """
        if table not in _ORDERS:
            raise NotFoundError(f"no run output named {table!r} (known: {', '.join(sorted(_ORDERS))})")
        t = self._ibis_res.table(table)
        t = t.filter(t.run_id == run_id)
        extra = {}
        if "structure_id" in t.columns:
            extra["structure_seq"] = t.structure_id.substr(1).cast("int64")
        if "trade_id" in t.columns:
            extra["trade_seq"] = t.trade_id.substr(1).cast("int64")
        return t.mutate(**extra) if extra else t

    def read_run_results(self, run_id: str, table: str, offset: int = 0, limit: int | None = None) -> pa.Table:
        """Read a run's output table, or the ``structure_snapshots`` view (RES-11), in step order.

        :param run_id: The run.
        :param table: The table or view.
        :param offset: Index of the first row.
        :param limit: Most rows; all when omitted.
        :returns: The rows, instants as aware UTC.
        """
        t = self._results_expr(run_id, table)
        expr = t.order_by(_ORDERS[table])
        if limit is not None or offset:
            expr = expr.limit(limit, offset=offset)
        out = expr.to_pyarrow()
        out = out.drop([c for c in ("structure_seq", "trade_seq") if c in out.column_names])
        return _with_zone(out)

    def count_run_results(self, run_id: str, table: str) -> int:
        """How many rows a run has in an output table or view.

        :param run_id: The run.
        :param table: The table or view.
        :returns: The count.
        """
        return self._results_expr(run_id, table).count().to_pyarrow().as_py()

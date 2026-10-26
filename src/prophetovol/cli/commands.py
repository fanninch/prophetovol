"""Data, registry, job and documentation commands: presentation over BacktestService (INT-40)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import click

from prophetovol.core.context import CallContext
from prophetovol.core.records import JobStatus, VersionState
from prophetovol.data.lifecycle import DataSelection
from prophetovol.runs.service import BacktestService


@contextmanager
def _service(state):
    """Open the command's service with CLI provenance and close it on every exit path."""
    context = CallContext.for_channel("cli")
    with BacktestService.open(state.home, context) as service:
        yield service, context


def _json(value):
    """Write a model or JSON-compatible value without lossy string conversion."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    click.echo(json.dumps(value, indent=2, ensure_ascii=False))


def _table(headers, rows):
    """A compact tab-separated table suitable for terminals and redirected output."""
    click.echo("\t".join(headers))
    for row in rows:
        click.echo("\t".join("-" if value is None else str(value) for value in row))


def _job(job):
    """Show a job outcome and return a nonzero exit for failure or cancellation."""
    click.echo(f"Job: {job.job_id} ({job.kind}) {job.status}")
    if job.status == JobStatus.FAILED:
        error = job.error if (job.result or {}).get("error_kind") == "expected" else "Unexpected failure; see logs/server.log in this home."
        raise click.ClickException(error or "Job failed")
    if job.status == JobStatus.CANCELLED:
        raise click.ClickException("Job cancelled")


def _quality(report, details=False):
    """Show every check with its severity and count, optionally including dates and examples."""
    if report is None:
        click.echo("No quality report is available yet.")
        return
    click.echo(f"Quality: {report.rows:,} rows, {report.dates} dates, {len(report.errors)} error checks, "
               f"{len(report.warnings)} warning checks")
    _table(["Check", "Severity", "Count", "Description"],
           [(c.name, c.severity, c.count, c.description) for c in report.checks])
    if details:
        _json(report)


@click.group()
def data():
    """Import, review and manage versioned market data."""


@data.command("import")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option("--commit", "choice", type=click.Choice(["replace", "add-new", "ask"]), default="ask", show_default=True,
              help="Commit policy; ask offers replace, add-new or cancel after review.")
@click.option("--data-source", default="ivolatility_eod", show_default=True)
@click.pass_obj
def data_import(state, paths, choice, data_source):
    """Import CSV files, folders or ZIP archives as one import, then review and commit.
    \f
    :param state: Shared CLI options.
    :param paths: Files, folders or archives for one import.
    :param choice: Commit policy, defaulting to interactive review.
    :param data_source: Configured vendor format.
    """
    with _service(state) as (svc, context):
        click.echo("Importing and validating files...")
        job = svc.import_files(list(paths), context, data_source=data_source)
        import_id = (job.result or {}).get("import_id")
        if import_id:
            click.echo(f"Import: {import_id}")
            _quality(svc.quality_report(import_id))
        _job(job)
        pairs = svc.overlap(import_id, context)
        click.echo(f"Overlap: {sum(p.active is not None for p in pairs)} of {len(pairs)} snapshots already active")
        _table(["As of", "Incoming contracts", "Active import", "Active contracts"],
               [(p.incoming.as_of.isoformat(), p.incoming.contracts, p.active.import_id if p.active else None,
                 p.active.contracts if p.active else None) for p in pairs])
        if choice == "ask":
            try:
                choice = click.prompt("Commit choice", type=click.Choice(["replace", "add-new", "cancel"]), default="cancel")
            except (click.Abort, KeyboardInterrupt):
                svc.commit_import(import_id, "cancel", context)
                click.echo("Staged import discarded.")
                raise
        committed = svc.commit_import(import_id, choice.replace("-", "_"), context)
        _job(committed)
        click.echo("Staged import discarded." if choice == "cancel" else f"Activated {committed.result['activated']} snapshots.")


@data.command("list")
@click.option("--underlying", default=None)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.pass_obj
def data_list(state, underlying, offset, limit):
    """List imports, newest first, including failed and discarded imports.
    \f
    :param state: Shared CLI options.
    :param underlying: Optional underlying filter.
    :param offset: First result offset.
    :param limit: Maximum imports to display.
    """
    with _service(state) as (svc, _):
        page = svc.page_imports(offset, limit, underlying)
        _table(["Import", "Underlying", "Status", "Rows", "From", "To"],
               [(i.import_id, i.underlying, i.status, i.rows, i.first_as_of_date, i.last_as_of_date) for i in page.items])
        click.echo(f"Showing {len(page.items)} of {page.total} imports (offset {page.offset}).")


@data.command("quality")
@click.argument("import_id")
@click.option("--details", is_flag=True, help="Include every per-date count and example as JSON.")
@click.pass_obj
def data_quality(state, import_id, details):
    """Show the permanently stored quality report of an import.
    \f
    :param state: Shared CLI options.
    :param import_id: Import to inspect.
    :param details: Include the complete report.
    """
    with _service(state) as (svc, _):
        _quality(svc.quality_report(import_id), details)


@data.command("coverage")
@click.option("--underlying", default=None, help="Default: every configured underlying.")
@click.option("--from", "start", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--to", "end", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--daily", is_flag=True, help="Also show daily imports, counts and quality flags.")
@click.pass_obj
def data_coverage(state, underlying, start, end, daily):
    """Summarize trading-day coverage by month; omitted bounds use active data's range.
    \f
    :param state: Shared CLI options.
    :param underlying: Optional underlying filter.
    :param start: Inclusive first date or earliest active date.
    :param end: Inclusive last date or latest active date.
    :param daily: Include daily details as well as the monthly table.
    """
    with _service(state) as (svc, context):
        for symbol in [underlying] if underlying else svc.list_underlyings():
            svc.underlying(symbol)
            versions = svc.data_versions(symbol, states=[VersionState.ACTIVE])
            if not versions and (start is None or end is None):
                click.echo(f"{symbol}: no active data; provide --from and --to to inspect missing coverage.")
                continue
            lo = start.date() if start else min(v.as_of_date for v in versions)
            hi = end.date() if end else max(v.as_of_date for v in versions)
            report = svc.coverage(symbol, lo, hi, context)
            click.echo(f"{symbol}: {lo} through {hi}")
            _table(["Month", "Trading days", "Covered", "Missing", "Non-trading", "Contracts", "Flagged days"],
                   [(m.month, m.trading_days, m.covered_days, m.missing_days, m.non_trading_days,
                     m.contracts, m.flagged_days) for m in report.months])
            if daily:
                _table(["Date", "Trading day", "Import", "Contracts", "Quality flags"],
                    [(d.day, d.trading_day, v.import_id if v else None, v.contracts if v else 0,
                      ", ".join(v.quality_flags) if v else "missing")
                     for d in report.days for v in (d.snapshots or [None])])


def _change(state, operation, import_id, underlying, start, end, yes):
    """Present an exact preview and submit it only after explicit confirmation."""
    selection = DataSelection(import_id=import_id, underlying=underlying,
                              start=start.date() if start else None, end=end.date() if end else None)
    with _service(state) as (svc, context):
        preview = svc.preview_data_change(operation, selection, context)
        click.echo(f"{operation.title()} preview: {len(preview.versions)} eligible versions; {len(preview.runs)} affected run/underlying pairs")
        _table(["Underlying", "As of", "Import", "State", "Contracts"],
               [(v.underlying, v.as_of.isoformat(), v.import_id, v.state, v.contracts) for v in preview.versions])
        _table(["Affected run", "Underlying", "Dates"],
               [(r.run_id, r.underlying, ", ".join(d.isoformat() for d in r.dates)) for r in preview.runs])
        if not preview.versions:
            click.echo("Nothing to change.")
            return
        if not yes and not click.confirm(f"Confirm {operation}?", default=False):
            click.echo("Cancelled; no data changed.")
            return
        method = svc.delete_data if operation == "delete" else svc.purge_data
        job = method(preview, context, confirmed=True)
        _job(job)
        click.echo(f"{operation.title()} completed: {job.result['versions']} versions.")


@data.command("delete")
@click.option("--underlying", required=True)
@click.option("--from", "start", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--to", "end", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--yes", is_flag=True, help="Explicitly confirm the displayed preview without prompting.")
@click.pass_obj
def data_delete(state, underlying, start, end, yes):
    """Deactivate active versions in an inclusive date range, keeping files and run results.
    \f
    :param state: Shared CLI options.
    :param underlying: Underlying to delete.
    :param start: Inclusive first date.
    :param end: Inclusive last date.
    :param yes: Explicit confirmation for scripts.
    """
    _change(state, "delete", None, underlying, start, end, yes)


@data.command("purge")
@click.option("--import-id", default=None, help="Purge eligible versions from one import, instead of a range.")
@click.option("--underlying", default=None)
@click.option("--from", "start", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--to", "end", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--yes", is_flag=True, help="Explicitly confirm the displayed preview without prompting.")
@click.pass_obj
def data_purge(state, import_id, underlying, start, end, yes):
    """Remove superseded/deleted data by import OR underlying/date range; retain active data.
    \f
    :param state: Shared CLI options.
    :param import_id: Import to purge, mutually exclusive with the date range.
    :param underlying: Underlying for a range selection.
    :param start: Inclusive first date.
    :param end: Inclusive last date.
    :param yes: Explicit confirmation for scripts.
    """
    _change(state, "purge", import_id, underlying, start, end, yes)


@click.group()
def registry():
    """Discover implementation names, descriptions, versions and parameter schemas."""


@registry.command("list")
@click.argument("kind", required=False)
@click.pass_obj
def registry_list(state, kind):
    """List registry types, or implementations of TYPE.
    \f
    :param state: Shared CLI options.
    :param kind: Optional registry type.
    """
    with _service(state) as (svc, context):
        if kind:
            _table(["Name", "Version", "Description"],
                   [(i.name, i.version, i.description) for i in svc.list_implementations(kind, context)])
        else:
            _table(["Type", "Implementations", "Description"],
                   [(r.kind, ", ".join(r.implementations), r.description) for r in svc.list_registries()])


@registry.command("show")
@click.argument("kind")
@click.argument("name")
@click.pass_obj
def registry_show(state, kind, name):
    """Show an implementation and its full JSON parameter schema.
    \f
    :param state: Shared CLI options.
    :param kind: Registry type.
    :param name: Implementation name.
    """
    with _service(state) as (svc, context):
        _json(svc.describe_implementation(kind, name, context))


@click.group()
def jobs():
    """Inspect persisted jobs. Foreground work is cancelled with Ctrl+C."""


@jobs.command("list")
@click.option("--status", multiple=True, type=click.Choice([s.value for s in JobStatus]))
@click.option("--offset", type=click.IntRange(min=0), default=0)
@click.option("--limit", type=click.IntRange(1, 500), default=50)
@click.pass_obj
def jobs_list(state, status, offset, limit):
    """List jobs, newest first, optionally filtering their status.
    \f
    :param state: Shared CLI options.
    :param status: Optional status filters.
    :param offset: First result offset.
    :param limit: Page size.
    """
    with _service(state) as (svc, _):
        page = svc.page_jobs(offset, limit, [JobStatus(s) for s in status] if status else None)
        _table(["Job", "Kind", "Status", "Done", "Total", "Progress"],
               [(j.job_id, j.kind, j.status, j.progress_done, j.progress_total, j.progress_label) for j in page.items])
        click.echo(f"Showing {len(page.items)} of {page.total} jobs (offset {page.offset}).")


@jobs.command("show")
@click.argument("job_id")
@click.pass_obj
def jobs_show(state, job_id):
    """Show job parameters, provenance, progress, result and outcome.
    \f
    :param state: Shared CLI options.
    :param job_id: Job to inspect.
    """
    with _service(state) as (svc, _):
        job = svc.get_job(job_id)
        body = job.model_dump(mode="json")
        if job.status == JobStatus.FAILED and job.error and (job.result or {}).get("error_kind") != "expected":
            body["error"] = "Unexpected failure; see logs/server.log in this home."
        _json(body)


@jobs.command("cancel")
@click.argument("job_id")
@click.pass_obj
def jobs_cancel(state, job_id):
    """Request cancellation; another process holding this home must be stopped there.
    \f
    :param state: Shared CLI options.
    :param job_id: Job to cancel.
    """
    with _service(state) as (svc, context):
        _json(svc.cancel_job(job_id, context))


@click.group()
def docs():
    """Generate reference documentation from models, registries and conventions."""


@docs.command("generate")
@click.option("--out", "output", type=click.Path(file_okay=False, path_type=Path), default="docs/reference", show_default=True)
@click.option("--check", is_flag=True, help="Fail if generated files are missing or stale; write nothing.")
@click.pass_obj
def docs_generate(state, output, check):
    """Write deterministic reStructuredText suitable for a later Sphinx site.
    \f
    :param state: Shared CLI options.
    :param output: Destination directory.
    :param check: Compare existing files without writing.
    """
    with _service(state) as (svc, context):
        paths = svc.generate_docs(output, context, check)
        click.echo(f"{'Checked' if check else 'Generated'} {len(paths)} reference documents in {output}.")

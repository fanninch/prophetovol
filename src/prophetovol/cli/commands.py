"""Data, registry, job and documentation commands: presentation over BacktestService (INT-40)."""

from __future__ import annotations

import json
import textwrap
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path

import click

from prophetovol.core.context import CallContext
from prophetovol.core.records import JobStatus, VersionState
from prophetovol.data.lifecycle import CoverageMonth, DataSelection
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
    """A table with columns aligned by padding; empty values show as ``-``."""
    cells = [list(headers)] + [["-" if value is None else str(value) for value in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    for row in cells:
        click.echo("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())


def _n(count, word, plural=None):
    """A count with its noun in the right number: ``1 date``, ``3 dates``."""
    return f"{count:,} {word if count == 1 else plural or word + 's'}"


def _local_time(instant):
    """A stored UTC instant as local wall-clock time, to the minute."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone().strftime("%Y-%m-%d %H:%M")


def _wrapped(text, indent):
    """Echo text wrapped to 100 columns under the given indent."""
    click.echo(textwrap.fill(text, width=100, initial_indent=indent, subsequent_indent=indent))


def _wrapped_items(lead, items, indent):
    """Echo comma-separated items wrapped to 100 columns, never splitting an item across lines."""
    line = indent + lead
    for i, item in enumerate(items):
        piece = item + ("," if i < len(items) - 1 else "")
        if len(line) + 1 + len(piece) > 100 and line.strip():
            click.echo(line)
            line = indent + piece
        else:
            line += ("" if line.endswith(" ") else " ") + piece
    click.echo(line)


def _job(job):
    """Show a job outcome and return a nonzero exit for failure or cancellation."""
    click.echo(f"Job: {job.job_id} ({job.kind}) {job.status}")
    if job.status == JobStatus.FAILED:
        error = job.error if (job.result or {}).get("error_kind") == "expected" else "Unexpected failure; see logs/server.log in this home."
        raise click.ClickException(error or "Job failed")
    if job.status == JobStatus.CANCELLED:
        raise click.ClickException("Job cancelled")


def _quality(report, details=False):
    """Show every check with its severity and count, optionally with its dates and examples."""
    if report is None:
        click.echo("No quality report is available yet.")
        return
    click.echo(f"Quality: {_n(report.rows, 'row')}, {_n(report.dates, 'date')}, "
               f"{_n(len(report.errors), 'error check')}, {_n(len(report.warnings), 'warning check')}")
    _table(["Check", "Severity", "Count", "Description"],
           [(c.name, c.severity, f"{c.count:,}", c.description) for c in report.checks])
    if not details:
        return
    for check in report.checks:
        click.echo("")
        click.echo(f"{check.name} ({check.severity}, {check.count:,}): {check.description}")
        if check.by_date:
            _wrapped_items(f"{_n(len(check.by_date), 'date')}:",
                           [f"{d.as_of_date or 'unparsed'} ({d.count:,})" for d in check.by_date], "  ")
        for example in check.examples:
            _wrapped("example: " + ", ".join(f"{k}={v}" for k, v in example.items()), "  ")


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
        clashes = [p for p in pairs if p.active is not None]
        if clashes:
            click.echo(f"Overlap: {len(clashes):,} of {_n(len(pairs), 'incoming snapshot')} already active")
            _table(["Date", "Incoming contracts", "Active import", "Active contracts"],
                   [(p.incoming.as_of_date, p.incoming.contracts, p.active.import_id, p.active.contracts)
                    for p in clashes])
        else:
            click.echo(f"Overlap: none; all {_n(len(pairs), 'incoming snapshot')} are new dates")
        if choice == "ask":
            try:
                choice = click.prompt("Commit choice", type=click.Choice(["replace", "add-new", "cancel"]), default="cancel")
            except (click.Abort, KeyboardInterrupt):
                svc.commit_import(import_id, "cancel", context)
                click.echo("Staged import discarded.")
                raise
        committed = svc.commit_import(import_id, choice.replace("-", "_"), context)
        _job(committed)
        click.echo("Staged import discarded." if choice == "cancel"
                   else f"Activated {_n(committed.result['activated'], 'snapshot')}.")


@data.command("list")
@click.option("--underlying", default=None)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.pass_obj
def data_list(state, underlying, offset, limit):
    """List imports, newest first, including failed and discarded imports.

    Rows and dates are as imported; Active days shows how many of the import's snapshots are active
    now, after later replacements, deletes and purges.
    \f
    :param state: Shared CLI options.
    :param underlying: Optional underlying filter.
    :param offset: First result offset.
    :param limit: Maximum imports to display.
    """
    with _service(state) as (svc, _):
        page = svc.page_imports(offset, limit, underlying)
        rows = []
        for i in page.items:
            versions = svc.data_versions(i.underlying, i.import_id) if i.underlying else []
            active = sum(v.state == VersionState.ACTIVE for v in versions)
            rows.append((i.import_id, i.underlying, i.status, f"{i.rows:,}", i.first_as_of_date, i.last_as_of_date,
                         f"{active:,} of {len(versions):,}" if versions else None))
        _table(["Import", "Underlying", "Status", "Rows", "From", "To", "Active days"], rows)
        click.echo(f"Showing {len(page.items)} of {_n(page.total, 'import')} (offset {page.offset}).")


@data.command("quality")
@click.argument("import_id")
@click.option("--details", is_flag=True, help="Also list each check's dates and examples.")
@click.option("--json", "as_json", is_flag=True, help="Print the complete report as JSON instead.")
@click.pass_obj
def data_quality(state, import_id, details, as_json):
    """Show the permanently stored quality report of an import.
    \f
    :param state: Shared CLI options.
    :param import_id: Import to inspect.
    :param details: Include each check's dates and examples.
    :param as_json: Print the complete report as JSON, for scripts.
    """
    with _service(state) as (svc, _):
        report = svc.quality_report(import_id)
        if as_json:
            _json(report)
        else:
            _quality(report, details)


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
            covered = sum(m.covered_days for m in report.months)
            trading = sum(m.trading_days for m in report.months)
            click.echo(f"{symbol}: {lo} through {hi}; {covered:,} of {_n(trading, 'trading day')} covered")
            _table(["Month", "Trading days", "Covered", "Missing", "Non-trading", "Contracts", "Flagged days"],
                   [(label, f"{m.trading_days:,}", f"{m.covered_days:,}", f"{m.missing_days:,}", m.non_trading_days,
                     f"{m.contracts:,}", m.flagged_days) for label, m in _collapse_empty_months(report.months)])
            if daily:
                _table(["Date", "Trading day", "Import", "Contracts", "Quality flags"],
                    [(d.day, d.trading_day, v.import_id if v else None, v.contracts if v else 0,
                      ", ".join(v.quality_flags) if v else "missing")
                     for d in report.days for v in (d.snapshots or [None])])


def _collapse_empty_months(months):
    """Merge each run of consecutive months without any data into one ``YYYY-MM to YYYY-MM`` row.

    :param months: Monthly coverage summaries in month order.
    :returns: ``(label, summary)`` pairs; a merged row's summary holds the run's totals.
    """
    rows, run = [], []

    def flush():
        if len(run) == 1:
            rows.append((run[0].month, run[0]))
        elif run:
            rows.append((f"{run[0].month} to {run[-1].month}", CoverageMonth(
                month=run[0].month, trading_days=sum(m.trading_days for m in run), covered_days=0,
                missing_days=sum(m.missing_days for m in run), non_trading_days=0, contracts=0, flagged_days=0)))
        run.clear()

    for month in months:
        if month.covered_days == 0 and month.non_trading_days == 0:
            run.append(month)
        else:
            flush()
            rows.append((month.month, month))
    flush()
    return rows


def _job_target(job):
    """What a job acted on, in a few words: an import, or an underlying and date range."""
    params, result = job.params or {}, job.result or {}
    if "import_id" in params:
        return params["import_id"] + (f" ({params['choice'].replace('_', '-')})" if "choice" in params else "")
    selection = (params.get("preview") or {}).get("selection")
    if selection:
        if selection.get("import_id"):
            return selection["import_id"]
        return f"{selection.get('underlying')} {selection.get('start')} to {selection.get('end')}"
    return result.get("import_id")


def _change(state, operation, import_id, underlying, start, end, yes):
    """Present an exact preview and submit it only after explicit confirmation."""
    selection = DataSelection(import_id=import_id, underlying=underlying,
                              start=start.date() if start else None, end=end.date() if end else None)
    with _service(state) as (svc, context):
        preview = svc.preview_data_change(operation, selection, context)
        click.echo(f"{operation.title()} preview: {_n(len(preview.versions), 'eligible version')}")
        if not preview.versions:
            click.echo("Nothing to change.")
            return
        _table(["Underlying", "Date", "Import", "State", "Contracts"],
               [(v.underlying, v.as_of_date, v.import_id, v.state, v.contracts) for v in preview.versions])
        if preview.runs:
            click.echo(f"Affected runs (results are kept and flagged data superseded): {len(preview.runs):,}")
            _table(["Run", "Underlying", "Dates"],
                   [(r.run_id, r.underlying, ", ".join(d.isoformat() for d in r.dates)) for r in preview.runs])
        else:
            click.echo("No runs affected.")
        if not yes and not click.confirm(f"Confirm {operation}?", default=False):
            click.echo("Cancelled; no data changed.")
            return
        method = svc.delete_data if operation == "delete" else svc.purge_data
        job = method(preview, context, confirmed=True)
        _job(job)
        click.echo(f"{operation.title()} completed: {_n(job.result['versions'], 'version')}.")


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
        _table(["Job", "Kind", "Status", "Started", "Target", "Progress"],
               [(j.job_id, j.kind, j.status, _local_time(j.started_at or j.created_at), _job_target(j),
                 " ".join(filter(None, [f"{j.progress_done}/{j.progress_total}" if j.progress_total else None,
                                        j.progress_label])) or None)
                for j in page.items])
        click.echo(f"Showing {len(page.items)} of {_n(page.total, 'job')} (offset {page.offset}).")


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

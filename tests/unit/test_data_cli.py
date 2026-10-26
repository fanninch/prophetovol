"""Phase 8 CLI flows on synthetic data, including failures and safe confirmations."""

import json
import re
import subprocess
import sys
import zipfile
from datetime import date

import pytest
from click.testing import CliRunner

from prophetovol.cli import main
from prophetovol.core.context import CallContext
from prophetovol.core.records import JobStatus, VersionState
from prophetovol.runs.service import BacktestService
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("cli")


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("cli-input")
    generate(GeneratorConfig(start_date=date(2024, 3, 18), end_date=date(2024, 3, 20),
                             monthly_count=1, weekly_count=1, dailies=False, rows_per_file=1), out)
    return out


def invoke(home, *args, input=None):
    return CliRunner().invoke(main, ["--home", str(home), *map(str, args)], input=input)


def import_data(home, files, choice="replace", input=None):
    result = invoke(home, "data", "import", files, "--commit", choice, input=input)
    assert result.exit_code == 0, result.output
    return re.search(r"Import: (imp_\w+)", result.output).group(1), result


def test_import_list_quality_coverage_and_jobs(tmp_path, files):
    home = tmp_path / "home"
    import_id, result = import_data(home, files)
    assert "Quality:" in result.output and "Overlap: none; all 3 incoming snapshots are new dates" in result.output
    assert "Date  " not in result.output  # no overlap table when nothing overlaps
    assert "Activated 3 snapshots." in result.output
    listing = invoke(home, "data", "list", "--underlying", "SPX", "--limit", 1)
    assert listing.exit_code == 0 and import_id in listing.output and "committed" in listing.output
    assert "3 of 3" in listing.output and "\t" not in listing.output
    quality = invoke(home, "data", "quality", import_id, "--json")
    assert quality.exit_code == 0 and json.loads(quality.output)["checks"]
    coverage = invoke(home, "data", "coverage", "--daily")
    assert coverage.exit_code == 0 and "2024-03" in coverage.output and import_id in coverage.output
    jobs = invoke(home, "jobs", "list", "--status", "succeeded")
    assert jobs.exit_code == 0 and "commit" in jobs.output and "ingest" in jobs.output
    assert f"{import_id} (replace)" in jobs.output and "Started" in jobs.output
    job_id = re.search(r"Job: (job_\w+)", result.output).group(1)
    shown = invoke(home, "jobs", "show", job_id)
    body = json.loads(shown.output)
    assert body["status"] == "succeeded" and body["channel"] == "cli"
    cancelled = invoke(home, "jobs", "cancel", job_id)
    assert cancelled.exit_code != 0 and "already finished" in cancelled.output


@pytest.mark.parametrize("answer,status", [("replace", "committed"), ("add-new", "committed"), ("cancel", "discarded")])
def test_ask_commit_choices(tmp_path, files, answer, status):
    home = tmp_path / "home"
    first, _ = import_data(home, files)
    second, result = import_data(home, files, "ask", input=answer+"\n")
    assert "Overlap: 3 of 3 incoming snapshots already active" in result.output and first in result.output
    assert "2024-03-18" in result.output and "T20:15" not in result.output  # dates, not UTC instants
    assert result.output.index("Quality:") < result.output.index("Commit choice")
    with BacktestService.open(home) as svc:
        assert svc.get_import(second).status == status
        active = svc.data_versions("SPX", states=[VersionState.ACTIVE])
        assert {v.import_id for v in active} == ({second} if answer == "replace" else {first})


def test_ask_eof_discards_and_reports_abort(tmp_path, files):
    home = tmp_path / "home"
    result = invoke(home, "data", "import", files, input="")
    assert result.exit_code != 0 and "Staged import discarded" in result.output
    with BacktestService.open(home) as svc:
        assert svc.page_imports().items[0].status == "discarded"


@pytest.mark.parametrize("form", ["files", "zip"])
def test_multi_file_and_zip_are_one_import(tmp_path, files, form):
    csvs = sorted(files.glob("*.csv"))
    if form == "zip":
        archive = tmp_path / "input.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for file in csvs:
                zf.write(file, "nested/"+file.name)
        inputs = [archive]
    else:
        inputs = csvs
    result = invoke(tmp_path / "home", "data", "import", *inputs, "--commit", "replace")
    assert result.exit_code == 0, result.output
    with BacktestService.open(tmp_path / "home") as svc:
        assert svc.page_imports().total == 1
        assert len(svc.page_imports().items[0].files) == len(csvs)


def test_delete_decline_then_confirm_and_purge(tmp_path, files):
    home = tmp_path / "home"
    import_id, _ = import_data(home, files)
    args = ("--underlying", "SPX", "--from", "2024-03-18", "--to", "2024-03-18")
    decline = invoke(home, "data", "delete", *args, input="n\n")
    assert decline.exit_code == 0 and "no data changed" in decline.output
    with BacktestService.open(home) as svc:
        assert len(svc.data_versions("SPX", states=[VersionState.ACTIVE])) == 3
    deleted = invoke(home, "data", "delete", *args, input="y\n")
    assert deleted.exit_code == 0 and "Delete completed: 1 version." in deleted.output
    assert "No runs affected." in deleted.output and "Affected runs" not in deleted.output
    assert "2 of 3" in invoke(home, "data", "list").output  # active days after the delete
    jobs = invoke(home, "jobs", "list").output
    assert "SPX 2024-03-18 to 2024-03-18" in jobs
    declined = invoke(home, "data", "purge", "--import-id", import_id, input="n\n")
    assert declined.exit_code == 0 and "no data changed" in declined.output
    purged = invoke(home, "data", "purge", *args, "--yes")
    assert purged.exit_code == 0 and "Purge completed: 1" in purged.output
    with BacktestService.open(home) as svc:
        assert svc.import_snapshot(import_id, date(2024, 3, 18)).num_rows == 0
        assert svc.import_snapshot(import_id, date(2024, 3, 19)).num_rows > 0
        assert svc.page_attempts(operation="data.delete").items[0].channel == "cli"


def test_quality_details_are_readable(tmp_path, files):
    home = tmp_path / "home"
    import_id, _ = import_data(home, files)
    with BacktestService.open(home) as svc:
        report = svc.quality_report(import_id)
    detailed = invoke(home, "data", "quality", import_id, "--details")
    assert detailed.exit_code == 0 and "{" not in detailed.output
    for check in report.checks:
        assert f"{check.name} ({check.severity}, {check.count:,}):" in detailed.output
    if any(c.examples for c in report.checks):
        assert "example: " in detailed.output
    if any(c.by_date for c in report.checks):
        assert "2024-03-1" in detailed.output


def test_coverage_collapses_months_without_data(tmp_path, files):
    home = tmp_path / "home"
    import_data(home, files)
    result = invoke(home, "data", "coverage", "--underlying", "SPX", "--from", "2023-11-01", "--to", "2024-03-31")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("2023-11 to 2024-02 ") for line in lines)
    assert not any(line.startswith(("2023-12 ", "2024-01 ")) for line in lines)
    assert "3 of " in lines[0] and "trading days covered" in lines[0]


def test_table_columns_are_aligned(capsys):
    from prophetovol.cli.commands import _n, _table
    _table(["A", "Longer"], [("value", None), ("x", 12)])
    assert capsys.readouterr().out.splitlines() == ["A      Longer", "value  -", "x      12"]
    assert (_n(1, "date"), _n(2, "date"), _n(1_000, "version")) == ("1 date", "2 dates", "1,000 versions")


def test_delete_preview_names_affected_runs_before_confirmation(tmp_path, files):
    home = tmp_path / "home"
    import_id, _ = import_data(home, files)
    with BacktestService.open(home) as svc:
        v = svc.data_versions("SPX")[0]
        svc.storage._cat.execute("INSERT INTO runs (run_id, status) VALUES ('run_example', 'completed')")
        svc.storage._cat.execute("INSERT INTO run_data_versions VALUES (?, ?, ?, ?)",
                                ["run_example", "SPX", v.as_of.replace(tzinfo=None), import_id])
    result = invoke(home, "data", "delete", "--underlying", "SPX", "--from", "2024-03-18", "--to", "2024-03-18", input="n\n")
    assert result.exit_code == 0 and result.output.index("run_example") < result.output.index("Confirm delete?")


def test_failed_validation_keeps_report_link_and_returns_nonzero(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("bad,header\n1,2\n", encoding="utf-8")
    result = invoke(tmp_path / "home", "data", "import", bad, "--commit", "replace")
    assert result.exit_code != 0 and "header" in result.output and "Import: imp_" in result.output
    assert "Traceback" not in result.output and "Commit choice" not in result.output
    import_id = re.search(r"Import: (imp_\w+)", result.output).group(1)
    quality = invoke(tmp_path / "home", "data", "quality", import_id)
    assert quality.exit_code == 0 and "error" in quality.output


@pytest.mark.parametrize("args,message", [
    (("data", "quality", "missing"), "no import"),
    (("data", "import", "missing.csv"), "does not exist"),
    (("data", "purge"), "supply an underlying"),
    (("data", "purge", "--import-id", "x", "--underlying", "SPX"), "choose an import OR"),
    (("registry", "list", "missing"), "no registry"),
    (("registry", "show", "settlement_source", "missing"), "no settlement_source"),
    (("jobs", "show", "missing"), "no job"),
    (("jobs", "cancel", "missing"), "no job"),
    (("data", "coverage", "--from", "2024-03-20", "--to", "2024-03-18"), "end must be"),
])
def test_expected_errors_are_readable(tmp_path, args, message):
    result = invoke(tmp_path / "home", *args)
    assert result.exit_code != 0 and message in result.output and "Traceback" not in result.output


def test_registry_commands_expose_schemas(tmp_path):
    home = tmp_path / "home"
    assert "settlement_source" in invoke(home, "registry", "list").output
    assert "pm_index_close" in invoke(home, "registry", "list", "settlement_source").output
    result = invoke(home, "registry", "show", "settlement_source", "pm_index_close")
    assert result.exit_code == 0
    assert json.loads(result.output)["params_schema"]["properties"] is not None


def test_docs_generation_and_stale_check(tmp_path):
    home, output = tmp_path / "home", tmp_path / "docs"
    result = invoke(home, "docs", "generate", "--out", output)
    assert result.exit_code == 0, result.output
    original = (output / "models.rst").read_bytes()
    assert b'"description"' in original and b'"required"' in original
    assert invoke(home, "docs", "generate", "--out", output, "--check").exit_code == 0
    (output / "models.rst").write_text("stale", encoding="utf-8")
    result = invoke(home, "docs", "generate", "--out", output, "--check")
    assert result.exit_code != 0 and "models.rst" in result.output
    assert (output / "models.rst").read_text(encoding="utf-8") == "stale"
    assert invoke(home, "docs", "generate", "--out", output).exit_code == 0
    assert (output / "models.rst").read_bytes() == original


def test_unexpected_exception_is_logged_not_exposed(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private diagnostic detail")
    monkeypatch.setattr(BacktestService, "page_imports", fail)
    result = invoke(tmp_path / "home", "data", "list")
    assert result.exit_code != 0 and "Unexpected error" in result.output
    assert "private diagnostic detail" not in result.output
    log = (tmp_path / "home" / "logs" / "server.log").read_text(encoding="utf-8")
    assert "private diagnostic detail" in log and "Traceback" in log


def test_unexpected_job_failure_is_logged_not_exposed(tmp_path, files, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private job detail")
    monkeypatch.setattr(BacktestService, "_ingest_job", fail)
    result = invoke(tmp_path / "home", "data", "import", files, "--commit", "replace")
    assert result.exit_code != 0 and "Unexpected failure" in result.output
    assert "private job detail" not in result.output
    job_id = re.search(r"Job: (job_\w+)", result.output).group(1)
    shown = invoke(tmp_path / "home", "jobs", "show", job_id)
    assert shown.exit_code == 0 and "private job detail" not in shown.output
    assert "Unexpected failure" in shown.output
    assert "private job detail" in (tmp_path / "home" / "logs" / "server.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("error", [BrokenPipeError(32, "Broken pipe"), OSError(22, "Invalid argument")])
def test_closed_output_pipe_exits_quietly(tmp_path, monkeypatch, error):
    import prophetovol.cli as cli
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(BacktestService, "page_imports", fail)
    monkeypatch.setattr(cli, "_stdout_closed", lambda exc: exc is error)
    result = invoke(tmp_path / "home", "data", "list")
    assert result.exit_code == 1 and "Unexpected error" not in result.output
    assert "Traceback" not in (tmp_path / "home" / "logs" / "server.log").read_text(encoding="utf-8")


def test_other_os_errors_stay_unexpected(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError(22, "private os detail")
    monkeypatch.setattr(BacktestService, "page_imports", fail)
    result = invoke(tmp_path / "home", "data", "list")
    assert result.exit_code != 0 and "Unexpected error" in result.output
    assert "private os detail" in (tmp_path / "home" / "logs" / "server.log").read_text(encoding="utf-8")


def test_cli_locked_home_names_remedy(tmp_path):
    home = tmp_path / "home"
    code = ("import sys; from prophetovol.runs.service import BacktestService; "
            f"s=BacktestService.open({str(home)!r}); print('ready',flush=True); sys.stdin.readline(); s.close()")
    holder = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        result = invoke(home, "data", "list")
        assert result.exit_code != 0 and "in use by another ProphetoVol process" in result.output
        assert "--home" in result.output and "stop" in result.output and "Traceback" not in result.output
    finally:
        holder.communicate("\n", timeout=20)


def test_help_hides_rest_fields(tmp_path):
    for args in [("data", "import"), ("data", "purge"), ("jobs", "cancel"), ("docs", "generate")]:
        result = invoke(tmp_path / "home", *args, "--help")
        assert result.exit_code == 0 and ":param" not in result.output


def test_unwritable_log_is_a_readable_error(tmp_path, monkeypatch):
    import logging
    def denied(*args, **kwargs):
        raise PermissionError(13, "Access denied")
    monkeypatch.setattr(logging, "FileHandler", denied)
    result = invoke(tmp_path / "home", "data", "list")
    assert result.exit_code != 0 and "Cannot open the home log" in result.output
    assert "Traceback" not in result.output


def test_ctrl_c_during_ingest_discards_partial_import(tmp_path, files, monkeypatch):
    from prophetovol.storage.duckdb.adapter import DuckDBAdapter
    original = DuckDBAdapter.write_market_partition
    def interrupt(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(DuckDBAdapter, "write_market_partition", interrupt)
    home = tmp_path / "home"
    result = invoke(home, "data", "import", files, "--commit", "replace")
    assert result.exit_code != 0 and "Aborted" in result.output
    with BacktestService.open(home) as svc:
        assert svc.page_jobs().items[0].status == JobStatus.CANCELLED
        assert svc.page_imports().items[0].status == "discarded"
    assert not list((home / "market").rglob("*.parquet"))

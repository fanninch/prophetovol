"""TEST-6: the ivolatility ingest adapter on synthetic files (DATA-1 to DATA-21, DATA-15)."""

from __future__ import annotations

import csv
import io
import math
import threading
import zipfile
from datetime import date, datetime, time, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ValidationFailed
from prophetovol.core.records import AttemptOutcome, ImportStatus, JobStatus, VersionState
from prophetovol.data.ivolatility import COLUMNS, osi_symbol
from prophetovol.data.schema import MARKET_SCHEMA
from prophetovol.pricing import black76
from prophetovol.pricing.time import expiry_dates, local_datetime, time_to_expiry_years, trading_days_to_expiry
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.reference.defaults import default_underlyings
from prophetovol.runs.jobs import JobContext, execute_job, new_job
from prophetovol.runs.service import BacktestService
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext(actor="alice", channel=Channel.CLI)
SPX = default_underlyings()["SPX"]
CAL = nyse_calendar()
NY = "America/New_York"
CURRENT = GeneratorConfig(start_date=date(2024, 3, 18), end_date=date(2024, 4, 5), rows_per_file=6000)
OLDER = GeneratorConfig(start_date=date(2008, 3, 10), end_date=date(2008, 3, 28), conventions="older")


def import_ok(svc: BacktestService, paths) -> str:
    job = svc.import_files(paths, CTX)
    assert job.status is JobStatus.SUCCEEDED, job.error
    return job.result["import_id"]


def market_rows(svc: BacktestService, import_id: str) -> pa.Table:
    files = sorted((svc.home / "market").rglob(f"{import_id}.parquet"))
    return pa.concat_tables([pq.read_table(f) for f in files]) if files else pa.table({})


def read_csv_rows(folder: Path) -> list[list[str]]:
    rows = []
    for f in sorted(folder.glob("data_download*.csv")):
        with open(f, newline="") as fh:
            rows += list(csv.reader(fh))[1:]
    return rows


def write_csv(path: Path, rows: list[list[str]], header=COLUMNS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return path


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    base = tmp_path_factory.mktemp("current")
    summary = generate(CURRENT, base / "files")
    svc = BacktestService.open(base / "home")
    import_id = import_ok(svc, [base / "files"])
    yield svc, import_id, market_rows(svc, import_id), summary, base
    svc.close()


@pytest.fixture(scope="module")
def older(tmp_path_factory):
    base = tmp_path_factory.mktemp("older")
    generate(OLDER, base / "files")
    svc = BacktestService.open(base / "home")
    import_id = import_ok(svc, [base / "files"])
    yield svc, import_id, market_rows(svc, import_id), base
    svc.close()


def col(table: pa.Table, name: str) -> list:
    return table[name].to_pylist()


class TestCurrentConventions:
    def test_staged_with_files_rows_versions_and_partitions(self, current):
        svc, import_id, rows, summary, base = current
        rec = svc.get_import(import_id)
        assert rec.status is ImportStatus.STAGED and rec.underlying == "SPX" and rec.data_source == "ivolatility_eod"
        assert len(rec.files) == len(summary.files) > 1 and all(len(f.sha256) == 64 for f in rec.files)
        assert rec.rows == summary.rows == rows.num_rows
        assert (rec.first_as_of_date, rec.last_as_of_date) == (date(2024, 3, 18), date(2024, 4, 5))
        versions = svc.storage.list_versions("SPX", import_id=import_id)
        assert len(versions) == summary.dates and {v.state for v in versions} == {VersionState.STAGED}
        assert sum(v.contracts for v in versions) == rows.num_rows
        assert versions[0].as_of == datetime(2024, 3, 18, 20, 15, tzinfo=timezone.utc)  # 16:15 EDT
        months = sorted(p.parent.name for p in (svc.home / "market").rglob(f"{import_id}.parquet"))
        assert months == ["month=03", "month=04"]
        assert rows.schema.equals(MARKET_SCHEMA)
        assert not (svc.home / "uploads" / import_id).exists()  # working folder removed

    def test_symbols_roots_and_osi(self, current):
        _, _, rows, _, _ = current
        assert set(col(rows, "vendor_root")) == {"SPX", "SPXW"} == set(col(rows, "root"))
        for r in rows.slice(0, 3000).to_pylist():
            assert r["osi_symbol"] == osi_symbol(r["root"], r["expiration"], r["option_type"], r["strike"])
            assert r["osi_symbol"] == r["vendor_symbol"]  # current files are OSI already

    def test_expiry_columns_match_the_reference_functions_row_by_row(self, current):
        _, _, rows, _, _ = current
        checked = 0
        for r in rows.to_pylist():
            e = expiry_dates(r["expiration"], r["settlement_style"], SPX.expiry_time(r["settlement_style"]), CAL, NY)
            assert (r["settlement_date"], r["last_trading_date"], r["expiry_local"]) == (
                e.settlement_date, e.last_trading_date, e.expiry_local)
            assert r["expiry_timestamp"] == e.expiry_timestamp
            as_of_local = local_datetime(r["as_of_date"], time(16, 15))
            assert r["as_of_local"] == as_of_local
            assert r["time_to_expiry_years"] == time_to_expiry_years(as_of_local, e.expiry_local)  # exact, SQL vs Python
            assert r["days_to_expiry"] == time_to_expiry_years(as_of_local, e.expiry_local) * 365
            assert r["trading_days_to_expiry"] == trading_days_to_expiry(r["as_of_date"], e.settlement_date, CAL)
            checked += 1
        assert checked == rows.num_rows

    def test_good_friday_weekly_settles_thursday(self, current):
        _, _, rows, _, _ = current
        thursday = rows.filter(pc.equal(rows["expiration"], pa.scalar(date(2024, 3, 28))))
        assert thursday.num_rows and set(col(thursday, "settlement_date")) == {date(2024, 3, 28)}

    def test_settlement_date_rows_have_no_iv_greeks_or_forward(self, current):
        _, _, rows, _, _ = current
        settling = rows.filter(pc.equal(rows["as_of_date"], rows["settlement_date"]))
        assert settling.num_rows
        for name in ("iv", "delta", "gamma", "vega", "theta", "forward", "forward_source", "vendor_iv"):
            assert settling[name].null_count == settling.num_rows, name
        assert set(col(settling, "vendor_delta")) == {0.0}  # the vendor's zeros are kept as given

    def test_vendor_forward_and_greeks_are_used_from_the_cutover(self, current):
        _, _, rows, _, _ = current
        live = rows.filter(pc.less(rows["as_of_date"], rows["settlement_date"]))
        assert set(col(live, "forward_source")) == {"vendor"} and set(col(live, "vendor_methodology")) == {"per_series_forward"}
        assert col(live, "forward") == col(live, "vendor_forward")
        assert set(col(rows, "greeks_source")) == {"vendor"}
        for name in ("delta", "gamma", "vega", "theta"):
            assert col(live, name) == col(live, f"vendor_{name}")
        assert col(live, "iv") == col(live, "vendor_iv")

    def test_parity_forwards_are_computed_as_a_check(self, current):
        _, _, rows, _, _ = current
        live = rows.filter(pc.and_(pc.less(rows["as_of_date"], rows["settlement_date"]), pc.is_valid(rows["parity_forward"])))
        rel = np.abs(np.array(col(live, "parity_forward")) / np.array(col(live, "vendor_forward")) - 1)
        assert live.num_rows and np.median(rel) < 5e-4

    def test_quality_warnings_and_version_flags(self, current):
        svc, import_id, rows, summary, _ = current
        report = svc.quality_report(import_id)
        assert not report.errors
        assert report.check("crossed_quote").count == summary.crossed_quotes
        assert report.check("zero_ask").count == summary.zero_asks
        assert report.check("vendor_flagged").count == summary.flagged
        flagged_dates = {d.as_of_date for d in report.check("crossed_quote").by_date}
        for v in svc.storage.list_versions("SPX", import_id=import_id):
            assert ("crossed_quote" in v.quality_flags) == (v.as_of_date in flagged_dates)

    def test_mean_price_is_kept_only_as_vendor_mid(self, current):
        _, _, rows, _, _ = current
        zero_bid = rows.filter(pc.equal(rows["bid"], 0.0))
        assert zero_bid.num_rows and set(col(zero_bid, "vendor_mid")) == {0.0}


class TestOlderConventions:
    def test_five_character_codes_are_normalized(self, older):
        svc, import_id, rows, _ = older
        assert svc.get_import(import_id).status is ImportStatus.STAGED
        assert all(len(s) == 5 for s in col(rows, "vendor_symbol"))
        mapping = set(zip(col(rows, "vendor_root"), col(rows, "root")))
        assert ("SPT", "SPX") in mapping and ("SKQ", "SPXW") in mapping and ("SZQ", "SPXW") in mapping
        assert any(v.startswith("JX") and r == "SPXW" for v, r in mapping)
        for r in rows.slice(0, 2000).to_pylist():
            assert r["osi_symbol"] == osi_symbol(r["root"], r["expiration"], r["option_type"], r["strike"])
        report = svc.quality_report(import_id)
        assert report.check("repeated_vendor_symbol").count > 0 and not report.errors

    def test_saturday_dated_monthlies(self, older):
        _, _, rows, _ = older
        def dates_for(exp):
            sub = rows.filter(pc.equal(rows["expiration"], pa.scalar(exp)))
            return set(col(sub, "settlement_date")), set(col(sub, "last_trading_date"))
        assert dates_for(date(2008, 3, 22)) == ({date(2008, 3, 20)}, {date(2008, 3, 19)})  # Good Friday 2008
        assert dates_for(date(2008, 4, 19)) == ({date(2008, 4, 18)}, {date(2008, 4, 17)})

    def test_parity_forwards_recover_the_true_forward(self, older):
        _, _, rows, _ = older
        live = rows.filter(pc.less(rows["as_of_date"], rows["settlement_date"]))
        assert set(col(live, "vendor_methodology")) == {"single_price"}
        assert col(live, "vendor_forward") == col(live, "index_level")
        assert set(col(live, "forward_source")) == {"parity"}
        t = np.array(col(live, "time_to_expiry_years"))
        true_f = np.array(col(live, "index_level")) * np.exp((OLDER.rate - OLDER.dividend_yield) * t)
        assert np.median(np.abs(np.array(col(live, "forward")) / true_f - 1)) < 2e-4
        assert np.median(np.abs(np.array(col(live, "parity_discount")) - np.exp(-OLDER.rate * t))) < 2e-3

    def test_greeks_are_recomputed_in_the_internal_conventions(self, older):
        _, _, rows, _ = older
        live = rows.filter(pc.is_valid(rows["iv"]))
        assert set(col(live, "greeks_source")) == {"recomputed"}
        g = black76.greeks(np.array(col(live, "forward")), np.array(col(live, "strike")),
                           np.array(col(live, "time_to_expiry_years")), np.array(col(live, "iv")),
                           np.array(col(live, "option_type")) == "call")
        for name in ("delta", "gamma", "vega", "theta"):
            assert np.allclose(np.array(col(live, name)), getattr(g, name), rtol=0, atol=1e-12)
        pairs: dict = {}
        for r in live.select(["as_of_date", "expiration", "strike", "option_type", "delta", "vendor_delta"]).to_pylist():
            pairs.setdefault((r["as_of_date"], r["expiration"], r["strike"]), {})[r["option_type"]] = r
        sums = [(p["call"]["delta"] - p["put"]["delta"], p["call"]["vendor_delta"] - p["put"]["vendor_delta"])
                for p in pairs.values() if len(p) == 2]
        assert sums and all(abs(internal - 1) < 1e-12 for internal, _ in sums)   # internal: undiscounted
        assert all(vendor < 1 for _, vendor in sums)                             # vendor's originals kept, discounted


def exact_chain(path: Path) -> tuple[float, float]:
    """A pre-2018 chain priced exactly with Black-76 (full precision), plus an expiration with one valid pair."""
    day, level, f_true, d_true, vol = date(2012, 6, 13), 1300.0, 1305.5, 0.995, 0.2
    rows = []
    for exp, strikes, all_bid in ((date(2012, 7, 20), range(1225, 1400, 25), True),
                                  (date(2012, 8, 17), range(1250, 1375, 25), False)):
        e = expiry_dates(exp, "PM", time(16, 0), CAL, NY)
        t = time_to_expiry_years(local_datetime(day, time(16, 15)), e.expiry_local)
        for k in strikes:
            for cp in ("C", "P"):
                price = float(black76.price(f_true, k, t, vol, cp == "C", d_true))
                bid = price - 0.05 if (all_bid or k == 1300) else 0.0
                code = osi_symbol("SPXW", exp, "call" if cp == "C" else "put", k)
                rows.append(["SPX", "CBOE", day.strftime("%m/%d/%Y"), repr(level), code, exp.strftime("%m/%d/%Y"),
                             f"{k:.1f}", cp, "E", repr(price + 0.05), repr(bid), repr(price), repr(vol), "0", "0",
                             repr(level), "", "0.5", "1", "0.001", "-0.1", "0"])
    write_csv(path, rows)
    return f_true, d_true


class TestParity:
    def test_exact_recovery_and_invalid_fit_fallback(self, tmp_path):
        f_true, d_true = exact_chain(tmp_path / "chain.csv")
        with BacktestService.open(tmp_path / "home") as svc:
            import_id = import_ok(svc, [tmp_path / "chain.csv"])
            rows = market_rows(svc, import_id)
            july = rows.filter(pc.equal(rows["expiration"], pa.scalar(date(2012, 7, 20))))
            assert set(col(july, "forward_source")) == {"parity"} and set(col(july, "parity_strikes")) == {6}
            assert col(july, "forward")[0] == pytest.approx(f_true, rel=1e-9)
            assert col(july, "parity_discount")[0] == pytest.approx(d_true, rel=1e-9)
            august = rows.filter(pc.equal(rows["expiration"], pa.scalar(date(2012, 8, 17))))
            assert set(col(august, "forward_source")) == {"vendor_single_price"}
            assert set(col(august, "forward")) == {1300.0} and august["parity_forward"].null_count == august.num_rows
            assert svc.quality_report(import_id).check("no_parity_forward").count == 1


@pytest.fixture(scope="module")
def small_files(tmp_path_factory):
    folder = tmp_path_factory.mktemp("small")
    generate(GeneratorConfig(start_date=date(2024, 6, 3), end_date=date(2024, 6, 14), monthly_count=2, weekly_count=2,
                             dailies=False), folder)
    return read_csv_rows(folder)


def failing_import(tmp_path, rows, header=COLUMNS):
    path = write_csv(tmp_path / "bad.csv", rows, header)
    svc = BacktestService.open(tmp_path / "home")
    job = svc.import_files([path], CTX)
    return svc, job


class TestValidationErrors:
    @pytest.mark.parametrize("check, mutate", [
        ("unparseable_value", lambda rows: rows[5].__setitem__(6, "abc")),
        ("several_underlyings", lambda rows: rows[5].__setitem__(0, "NDX")),
        ("unknown_root", lambda rows: rows[5].__setitem__(4, "XYZW  " + rows[5][4][6:])),
        ("not_european", lambda rows: rows[5].__setitem__(8, "A")),
        ("duplicate_contract", lambda rows: rows.append(list(rows[5]))),
    ])
    def test_errors_fail_the_import_and_write_nothing(self, tmp_path, small_files, check, mutate):
        rows = [list(r) for r in small_files]
        mutate(rows)
        svc, job = failing_import(tmp_path, rows)
        try:
            assert job.status is JobStatus.FAILED and check in job.error
            rec = svc.page_imports().items[0]
            assert rec.status is ImportStatus.FAILED and check in rec.error
            assert svc.quality_report(rec.import_id).check(check).count >= 1
            assert not list((svc.home / "market").rglob("*.parquet"))
            assert svc.storage.list_versions("SPX") == []
        finally:
            svc.close()

    def test_unknown_underlying(self, tmp_path, small_files):
        svc, job = failing_import(tmp_path, [["RUT"] + r[1:] for r in small_files])
        try:
            assert job.status is JobStatus.FAILED and "unknown_underlying" in job.error
        finally:
            svc.close()

    def test_misnamed_header(self, tmp_path, small_files):
        header = list(COLUMNS)
        header[12] = "implied vol"
        svc, job = failing_import(tmp_path, small_files, header)
        try:
            assert job.status is JobStatus.FAILED and "header" in job.error
            example = svc.quality_report(svc.page_imports().items[0].import_id).check("header").examples[0]
            assert example["missing"] == ["iv"] and example["unexpected"] == ["implied vol"]
        finally:
            svc.close()


class TestValidationWarnings:
    def test_warnings_keep_the_import_and_flag_the_dates(self, tmp_path, small_files):
        rows = [list(r) for r in small_files]
        dates = sorted({r[2] for r in rows}, key=lambda s: datetime.strptime(s, "%m/%d/%Y"))
        drop, thin = dates[3], dates[6]
        thin_rows = [r for r in rows if r[2] == thin]
        rows = [r for r in rows if r[2] not in (drop, thin)] + thin_rows[: len(thin_rows) // 10]
        live = next(r for r in rows if r[12] not in ("-1",))
        live[12] = "-1"                                    # IV -1 before settlement
        rows[0][15] = ""                                   # missing stock price for iv
        saturday = [list(r) for r in rows if r[2] == dates[0]][:4]
        for r in saturday:
            r[2] = "06/08/2024"                            # a Saturday
        rows += saturday
        path = write_csv(tmp_path / "warn.csv", rows)
        with BacktestService.open(tmp_path / "home") as svc:
            import_id = import_ok(svc, [path])
            report = svc.quality_report(import_id)
            assert not report.errors
            for check in ("missing_trading_day", "low_contract_count", "iv_minus_one_before_settlement",
                          "missing_vendor_forward", "not_a_trading_day"):
                assert report.check(check) and report.check(check).count >= 1, check
            assert [d.as_of_date for d in report.check("missing_trading_day").by_date] == [
                datetime.strptime(drop, "%m/%d/%Y").date()]
            thin_version = next(v for v in svc.storage.list_versions("SPX", import_id=import_id)
                                if v.as_of_date == datetime.strptime(thin, "%m/%d/%Y").date())
            assert "low_contract_count" in thin_version.quality_flags


class TestInputs:
    def test_folder_files_and_zip_give_the_same_rows(self, tmp_path):
        generate(CURRENT.model_copy(update={"end_date": date(2024, 3, 22)}), tmp_path / "f")
        files = sorted((tmp_path / "f").glob("*.csv"))
        archive = tmp_path / "all.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for f in files:
                zf.write(f, f"inner/{f.name}")
        with BacktestService.open(tmp_path / "home") as svc:
            counts = {}
            for label, paths in (("folder", [tmp_path / "f"]), ("files", files), ("zip", [archive])):
                import_id = import_ok(svc, paths)
                counts[label] = svc.get_import(import_id).rows
            assert len(set(counts.values())) == 1
            zipped = svc.get_import(import_id)
            assert all(f.name.startswith("all.zip/inner/") for f in zipped.files)
            report = svc.quality_report(import_id)
            assert report.check("file_already_imported").count == len(files)  # DATA-12: same contents as before

    def test_refused_inputs_are_audited_and_create_nothing(self, tmp_path):
        generate(CURRENT.model_copy(update={"end_date": date(2024, 3, 19)}), tmp_path / "f")
        with BacktestService.open(tmp_path / "home") as svc:
            svc.max_import_bytes = 1000
            with pytest.raises(ValidationFailed, match="limit"):
                svc.import_files([tmp_path / "f"], CTX)
            with pytest.raises(ValidationFailed, match="does not exist"):
                svc.import_files([tmp_path / "nope.csv"], CTX)
            assert svc.page_imports().total == 0
            attempts = svc.page_attempts(operation="data.import").items
            assert [a.outcome for a in attempts] == [AttemptOutcome.REJECTED, AttemptOutcome.REJECTED]


class TestJobs:
    def test_cancellation_between_partitions_discards_everything(self, tmp_path):
        generate(GeneratorConfig(start_date=date(2024, 5, 27), end_date=date(2024, 6, 7), monthly_count=2,
                                 weekly_count=1, dailies=False), tmp_path / "f")
        with BacktestService.open(tmp_path / "home") as svc:
            cancel = threading.Event()
            original = svc.storage.write_market_partition

            def write_then_cancel(*args, **kwargs):
                original(*args, **kwargs)
                cancel.set()

            svc.storage.write_market_partition = write_then_cancel
            record = new_job("ingest", {"paths": [str(tmp_path / "f")], "data_source": "ivolatility_eod"}, CTX)
            svc.storage.insert_job(record)
            final = execute_job(record, svc._ingest_job, svc.storage, cancel)
            assert final.status is JobStatus.CANCELLED
            imp = svc.page_imports().items[0]
            assert imp.status is ImportStatus.DISCARDED and imp.error == "cancelled during ingest"
            assert not list((svc.home / "market").rglob("*.parquet"))

    def test_background_import(self, tmp_path):
        generate(CURRENT.model_copy(update={"end_date": date(2024, 3, 19)}), tmp_path / "f")
        with BacktestService.open(tmp_path / "home") as svc:
            svc.start_jobs(svc.job_handlers())
            job = svc.import_files([tmp_path / "f"], CTX, background=True)
            assert job.status is JobStatus.QUEUED and svc.jobs.wait(job.job_id, 60)
            done = svc.get_job(job.job_id)
            assert done.status is JobStatus.SUCCEEDED and done.progress_label == "staged"
            assert svc.get_import(done.result["import_id"]).status is ImportStatus.STAGED

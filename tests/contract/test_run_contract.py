"""Phase 14 storage contract: runs, their provenance, and atomic result writes (RUN-23, RUN-30, TEST-7)."""

from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pytest

from prophetovol.core.context import Channel
from prophetovol.core.errors import ImmutableEntityError, NotFoundError
from prophetovol.core.records import RunRecord, RunStatus
from prophetovol.results.recorder import RunRecorder
from tests.contract.test_lifecycle_contract import D1, D2, stage

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def record(run_id="run_a", created=T0, **changes) -> RunRecord:
    return RunRecord(run_id=run_id, status=RunStatus.QUEUED, spec_id="s", spec_version=2, spec_hash="ab" * 32,
                     config={"start_date": "2024-01-02", "end_date": "2024-01-03", "capital": 1e6}, config_hash="cd" * 32,
                     underlying="SPX", underlying_version=1, data_source="ivolatility_eod", data_source_version=1,
                     calendar_version="4.13.2", software_versions={"prophetovol": "0.1.0"},
                     registry_versions={"fill_model/mid": "1", "constructor/rules": "1"}, steps_total=2,
                     actor="alice", channel=Channel.CLI, created_at=created).model_copy(update=changes)


def outputs(run_id="run_a", steps=2) -> dict[str, pa.Table]:
    rec = RunRecorder(run_id)
    for step in range(1, steps + 1):
        t = datetime(2024, 1, 1 + step, 20, 15, tzinfo=timezone.utc)
        base = {k: None for k in ("osi_symbol", "root", "vendor_symbol", "vendor_root", "settlement_style", "expiration",
                                  "settlement_date", "last_trading_date", "expiry_timestamp", "strike", "option_type",
                                  "time_to_expiry_years", "days_to_expiry", "trading_days_to_expiry", "bid", "ask",
                                  "iv", "forward", "forward_source", "gamma", "vega", "theta", "dollar_gamma_1pct",
                                  "dollar_vega", "dollar_theta")}
        for leg, value in (("a", 100.0 * step), ("hedge", 10.0)):
            rec.add("position_snapshots", **base, step=step, as_of=t, structure_id="S1", leg_id=leg,
                    position_key=f"S1/{leg}", quantity=1.0, mark=1.0, mark_source="mid", index_level=5000.0,
                    market_value=value, cash_flow=0.0, fees=0.0, period_pnl=value, cumulative_pnl=value * step,
                    delta=0.5, dollar_delta=1.0, flags=["stale_mark"] if step == 2 else [])
        rec.add("portfolio_snapshots", step=step, as_of=t, index_level=5000.0, market_value=0.0, cash_flow=0.0,
                fees=0.0, period_pnl=1.0, cumulative_pnl=1.0, equity=1e6, period_return=0.0, dollar_delta=0.0,
                dollar_gamma_1pct=0.0, dollar_vega=0.0, dollar_theta=0.0, open_structures=1, contracts_held=1.0,
                worst_stress_loss=None, flags=[])
        rec.add("trades", trade_id=f"T{11 - step * 5}", step=step, as_of=t, structure_id="S1", leg_id="a",
                position_key="S1/a", osi_symbol="X", action="open", quantity=1.0, price=1.0, fees=0.0, cash_flow=-100.0,
                reason="entry", forced=False)
        rec.event(step, t, "entry", f"step {step}", details_key=step)
    rec.set_structure("S1", parent_id=None, units=1.0, opened_step=1, opened_as_of=T0, closed_step=None,
                      closed_as_of=None, status="open", cumulative_pnl=1.0)
    return rec.tables()


def test_runs_round_trip_with_their_inputs(adapter):
    stage(adapter, "imp", (D1, D2))
    adapter.commit_import("imp", "replace")
    versions = adapter.list_versions("SPX", "imp")
    adapter.create_run(record(), versions)
    got = adapter.get_run("run_a")
    assert got == record() and got.created_at.tzinfo is not None
    assert [(v.import_id, v.as_of_date) for v in adapter.run_data_versions("run_a")] == [("imp", D1), ("imp", D2)]
    later = got.model_copy(update={"status": RunStatus.COMPLETED, "steps_completed": 2, "final_pnl": 12.5,
                                   "finished_at": T0 + timedelta(minutes=1), "last_as_of": T0, "job_id": "job_x"})
    adapter.update_run(later)
    assert adapter.get_run("run_a") == later
    with pytest.raises(NotFoundError, match="no run 'nope'"):
        adapter.get_run("nope")


def test_runs_page_newest_first_with_status_filter(adapter):
    for i, status in enumerate([RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED]):
        adapter.create_run(record(f"run_{i}", created=T0 + timedelta(minutes=i), status=status), [])
    assert [r.run_id for r in adapter.page_runs().items] == ["run_2", "run_1", "run_0"]
    page = adapter.page_runs(statuses=[RunStatus.COMPLETED], limit=1)
    assert page.total == 2 and [r.run_id for r in page.items] == ["run_2"]


def test_results_round_trip_in_order(adapter):
    adapter.create_run(record(), [])
    tables = outputs()
    adapter.write_run_results("run_a", tables)
    for name, table in tables.items():
        assert adapter.read_run_results("run_a", name).to_pylist() == sorted(
            table.to_pylist(), key=lambda r: (r.get("step", 0), r.get("trade_id", "")[1:].zfill(4)))
    trades = adapter.read_run_results("run_a", "trades")
    assert trades.column("trade_id").to_pylist() == ["T6", "T1"]  # step order, then numeric trade order
    assert adapter.read_run_results("run_a", "position_snapshots").column("flags").to_pylist()[2] == ["stale_mark"]
    assert adapter.read_run_results("run_a", "events", offset=1, limit=1).column("seq").to_pylist() == [2]
    assert adapter.count_run_results("run_a", "position_snapshots") == 4
    assert adapter.count_run_results("other", "events") == 0


def test_structure_snapshots_view(adapter):
    adapter.create_run(record(), [])
    adapter.write_run_results("run_a", outputs())
    view = adapter.read_run_results("run_a", "structure_snapshots").to_pylist()
    # step 1: 100 + 10; step 2: 200 + 10, cumulative 110 + 210
    assert [(v["step"], v["market_value"], v["period_pnl"], v["cumulative_pnl"], v["legs_held"]) for v in view] == [
        (1, 110.0, 110.0, 110.0, 1), (2, 210.0, 210.0, 320.0, 1)]


def test_results_are_written_once_and_atomically(adapter):
    adapter.create_run(record(), [])
    broken = outputs()
    broken["trades"] = broken["trades"].rename_columns([*broken["trades"].column_names[:-1], "not_a_column"])
    with pytest.raises(Exception):
        adapter.write_run_results("run_a", broken)
    assert all(adapter.count_run_results("run_a", t) == 0 for t in broken)  # nothing from before the failure
    adapter.write_run_results("run_a", outputs())
    with pytest.raises(ImmutableEntityError, match="already has stored results"):
        adapter.write_run_results("run_a", outputs())
    with pytest.raises(NotFoundError, match="no run output named 'nope'"):
        adapter.read_run_results("run_a", "nope")


def test_results_tables_match_the_record_models(adapter):
    from prophetovol.results.records import RECORD_MODELS
    for name, model in RECORD_MODELS.items():
        assert adapter.read_run_results("none", name).column_names == list(model.model_fields), name

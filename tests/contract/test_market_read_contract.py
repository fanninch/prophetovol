"""Phase 10 storage contract: reading exact data versions in chunks, for runs (plan §4.6, decision 30)."""

from datetime import date, datetime, timezone

import pyarrow as pa
import pytest

from prophetovol.core.errors import NotFoundError
from prophetovol.core.records import ImportStatus, VersionState
from prophetovol.data.lifecycle import CommitChoice
from tests.contract.test_adapter_contract import make_import, version

D1, D2, D3 = date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2)


def chain(day: date, level: float, bid: float) -> pa.Table:
    """Four contracts, written out of order, at two expirations 10 and 40 days out."""
    as_of = datetime(day.year, day.month, day.day, 20, 15, tzinfo=timezone.utc)
    rows = [("SPXW", 10.0, "put", 5000.0), ("SPX", 40.0, "call", 5100.0), ("SPXW", 10.0, "call", 5000.0),
            ("SPX", 40.0, "call", 5000.0)]
    return pa.table({
        "as_of_date": pa.array([day] * 4, pa.date32()),
        "as_of": pa.array([as_of] * 4, pa.timestamp("us", tz="UTC")),
        "root": [r[0] for r in rows],
        "expiration": pa.array([date(2024, 3, 15)] * 4, pa.date32()),
        "option_type": [r[2] for r in rows],
        "strike": [r[3] for r in rows],
        "days_to_expiry": [r[1] for r in rows],
        "bid": [bid] * 4,
        "index_level": [level] * 4,
    })


def load(adapter, name, days, bid, choice=CommitChoice.REPLACE):
    record = make_import(name)
    record.status = ImportStatus.STAGED
    record.quality_report = {"checks": []}
    adapter.create_import(record)
    for (year, month) in sorted({(d.year, d.month) for d in days}):
        adapter.write_market_partition(name, "SPX", year, month, pa.concat_tables(
            [chain(d, 5000.0 + d.day, bid) for d in days if (d.year, d.month) == (year, month)]))
    adapter.record_staged_versions([version(name, d, 4) for d in days])
    adapter.commit_import(name, choice)
    return [v for v in adapter.list_versions("SPX", name)]


def test_reads_exactly_the_given_versions_in_order_across_months(adapter):
    first = load(adapter, "first", [D1, D2, D3], bid=1.0)
    table = adapter.read_market_chunk("SPX", first, ["as_of_date", "root", "option_type", "strike", "bid"])
    assert table.column_names == ["as_of_date", "root", "option_type", "strike", "bid"]
    assert table.num_rows == 12
    # ordered by as-of time, then root, expiration, option type and strike
    assert table.slice(0, 4).to_pylist() == [
        {"as_of_date": D1, "root": "SPX", "option_type": "call", "strike": 5000.0, "bid": 1.0},
        {"as_of_date": D1, "root": "SPX", "option_type": "call", "strike": 5100.0, "bid": 1.0},
        {"as_of_date": D1, "root": "SPXW", "option_type": "call", "strike": 5000.0, "bid": 1.0},
        {"as_of_date": D1, "root": "SPXW", "option_type": "put", "strike": 5000.0, "bid": 1.0}]
    assert table.column("as_of_date").to_pylist() == [D1] * 4 + [D2] * 4 + [D3] * 4
    only_d2 = adapter.read_market_chunk("SPX", [first[1]])
    assert set(only_d2.column("as_of_date").to_pylist()) == {D2}


def test_superseded_versions_stay_readable_by_reference(adapter):
    first = load(adapter, "first", [D1, D2], bid=1.0)
    load(adapter, "second", [D2], bid=2.0)
    assert {v.state for v in adapter.list_versions("SPX", "first") if v.as_of_date == D2} == {VersionState.SUPERSEDED}
    old = adapter.read_market_chunk("SPX", first, ["as_of_date", "bid"])
    assert old.column("bid").to_pylist() == [1.0] * 8
    mixed = [first[0]] + adapter.list_versions("SPX", "second")
    assert adapter.read_market_chunk("SPX", mixed, ["bid"]).column("bid").to_pylist() == [1.0] * 4 + [2.0] * 4


def test_horizon_filter_and_index_levels(adapter):
    first = load(adapter, "first", [D1, D2], bid=1.0)
    near = adapter.read_market_chunk("SPX", first, ["days_to_expiry"], max_days_to_expiry=20)
    assert near.column("days_to_expiry").to_pylist() == [10.0] * 4
    assert adapter.read_market_chunk("SPX", first, ["bid"], max_days_to_expiry=1).num_rows == 0
    levels = adapter.read_index_levels("SPX", first)
    assert levels == {first[0].as_of: 5031.0, first[1].as_of: 5001.0}
    assert all(k.tzinfo is not None for k in levels)


def test_purged_versions_cannot_be_read(adapter):
    first = load(adapter, "first", [D1, D2], bid=1.0)
    load(adapter, "second", [D1, D2], bid=2.0)
    from prophetovol.data.lifecycle import DataSelection
    adapter.apply_change(adapter.preview_change("purge", DataSelection(import_id="first")))
    with pytest.raises(NotFoundError, match="import first is no longer stored"):
        adapter.read_market_chunk("SPX", first)
    with pytest.raises(NotFoundError):
        adapter.read_index_levels("SPX", first)


def test_no_versions_reads_nothing(adapter):
    assert adapter.read_market_chunk("SPX", []).num_rows == 0
    assert adapter.read_index_levels("SPX", []) == {}

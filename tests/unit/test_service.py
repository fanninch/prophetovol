"""BacktestService: opening, seeding reference data, readers, and a home held by another process (INT-41)."""

import subprocess
import sys
import textwrap

import pytest

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import HomeLockedError, NotFoundError
from prophetovol.runs.service import DATA_SOURCE, UNDERLYING, BacktestService


def test_open_creates_home_and_seeds_reference_data(tmp_path):
    home = tmp_path / "home"
    with BacktestService.open(home, CallContext(actor="alice", channel=Channel.CLI)) as svc:
        assert svc.home == home.resolve()
        assert (home / "catalog.duckdb").is_file() and (home / "results.duckdb").is_file()
        assert svc.list_underlyings() == ["SPX"] and svc.list_data_sources() == ["ivolatility_eod"]
        spx = svc.underlying("SPX")
        assert len(spx.roots) == 40 and spx.normalized_roots() == ["SPX", "SPXW"]
        assert svc.data_source("ivolatility_eod").parity_strikes == 6
        seeded = svc.storage.get_definition(UNDERLYING, "SPX")
        assert (seeded.version, seeded.actor, seeded.channel) == (1, "alice", Channel.CLI)


def test_reopening_does_not_reseed_or_overwrite_changes(tmp_path):
    home = tmp_path / "home"
    with BacktestService.open(home) as svc:
        body = svc.storage.get_definition(UNDERLYING, "SPX").body
        body["description"] = "edited by the user"
        svc.storage.save_definition(UNDERLYING, "SPX", body, CallContext(actor="bob", channel=Channel.GUI))
    with BacktestService.open(home) as svc:
        assert [v.version for v in svc.storage.list_definition_versions(UNDERLYING, "SPX")] == [1, 2]
        assert svc.underlying("SPX").description == "edited by the user"
        assert svc.underlying("SPX", version=1).description != "edited by the user"
        assert len(svc.storage.list_definition_versions(DATA_SOURCE, "ivolatility_eod")) == 1


def test_open_uses_prophetovol_home(tmp_home):
    with BacktestService.open() as svc:
        assert svc.home == tmp_home.resolve()


def test_unknown_reference_data(tmp_path):
    with BacktestService.open(tmp_path / "home") as svc:
        with pytest.raises(NotFoundError):
            svc.underlying("NDX")


def test_reader_shares_the_databases(tmp_path):
    with BacktestService.open(tmp_path / "home") as svc:
        reader = svc.reader()
        assert reader.list_underlyings() == ["SPX"] and reader.home == svc.home
        reader.close()
        assert svc.list_underlyings() == ["SPX"]


def test_home_held_by_another_process_is_reported(tmp_path):
    home = tmp_path / "home"
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys
            from prophetovol.runs.service import BacktestService
            svc = BacktestService.open({str(home)!r})
            print("ready", flush=True)
            sys.stdin.readline()
            svc.close()
        """)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(HomeLockedError, match="in use by another ProphetoVol process") as info:
            BacktestService.open(home)
        assert "--home" in str(info.value)
    finally:
        holder.communicate("\n", timeout=30)
    with BacktestService.open(home) as svc:  # free again once the other process has closed it
        assert svc.list_underlyings() == ["SPX"]

"""DuckDB-specific storage behaviour: migrations, the market file layout, and refusing to discard used data."""

from datetime import date, datetime, timezone

import duckdb
import pyarrow.parquet as pq
import pytest

from prophetovol.core.errors import ConfigurationError, ImmutableEntityError
from prophetovol.storage.duckdb.adapter import DuckDBAdapter
from prophetovol.storage.duckdb.schema import CATALOG_MIGRATIONS, Migration, apply_migrations, schema_version

from tests.contract.test_adapter_contract import make_import, snapshot_table, version


class TestMigrations:
    def test_applied_in_order_and_only_once(self, tmp_path):
        con = duckdb.connect(str(tmp_path / "x.duckdb"))
        v1 = (Migration(1, "one", ("CREATE TABLE a (x INTEGER)",)),)
        assert schema_version(con) == 0
        assert apply_migrations(con, v1) == 1
        assert apply_migrations(con, v1) == 1  # idempotent
        v2 = v1 + (Migration(2, "two", ("CREATE TABLE b (y INTEGER)",)),)
        assert apply_migrations(con, v2) == 2
        assert con.execute("SELECT version, description FROM schema_version ORDER BY 1").fetchall() == [
            (1, "one"), (2, "two")]

    def test_a_failing_migration_changes_nothing(self, tmp_path):
        con = duckdb.connect(str(tmp_path / "x.duckdb"))
        bad = (Migration(1, "bad", ("CREATE TABLE a (x INTEGER)", "THIS IS NOT SQL")),)
        with pytest.raises(duckdb.Error):
            apply_migrations(con, bad)
        assert schema_version(con) == 0
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'a'").fetchone()[0] == 0

    def test_newer_database_and_bad_numbering_are_refused(self, tmp_path):
        con = duckdb.connect(str(tmp_path / "x.duckdb"))
        apply_migrations(con, (Migration(1, "1", ()), Migration(2, "2", ())))
        with pytest.raises(ConfigurationError, match="newer than this ProphetoVol supports"):
            apply_migrations(con, (Migration(1, "1", ()),))
        with pytest.raises(ConfigurationError, match="numbered"):
            apply_migrations(con, (Migration(2, "2", ()),))

    def test_catalog_migrations_are_numbered(self):
        assert [m.version for m in CATALOG_MIGRATIONS] == list(range(1, len(CATALOG_MIGRATIONS) + 1))


@pytest.fixture
def duck(tmp_path):
    a = DuckDBAdapter.open(tmp_path / "home")
    yield a
    a.close()


def test_market_file_layout(duck):
    duck.create_import(make_import("imp_1"))
    duck.write_market_partition("imp_1", "SPX", 2024, 3, snapshot_table(date(2024, 3, 1)))
    path = duck.home / "market" / "underlying=SPX" / "year=2024" / "month=03" / "imp_1.parquet"
    assert path.is_file()
    assert pq.read_metadata(path).num_rows == 3
    assert not list(path.parent.glob("*.partial"))


def test_instants_are_stored_as_naive_utc(duck):
    duck.create_import(make_import("imp_1"))
    stored = duck._cat.execute("SELECT created_at FROM imports").fetchone()[0]
    assert stored == datetime(2026, 10, 25, 12, 0) and stored.tzinfo is None


def test_an_activated_import_cannot_be_discarded(duck):
    duck.create_import(make_import("imp_1"))
    duck.write_market_partition("imp_1", "SPX", 2024, 1, snapshot_table(date(2024, 1, 2)))
    duck.record_staged_versions([version("imp_1", date(2024, 1, 2))])
    duck._cat.execute("UPDATE data_versions SET state = 'active'")  # activation arrives with Phase 7
    with pytest.raises(ImmutableEntityError, match="only staged imports can be discarded"):
        duck.discard_import("imp_1")
    assert (duck.home / "market" / "underlying=SPX" / "year=2024" / "month=01" / "imp_1.parquet").is_file()


def test_naive_instants_are_rejected(duck):
    rec = make_import("imp_1")
    rec.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        duck.create_import(rec)

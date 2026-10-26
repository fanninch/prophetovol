"""The registry mechanism (REG-2, REG-3) and the settlement sources (REF-20, REF-21)."""

import pytest
from pydantic import BaseModel, Field

from prophetovol.core.errors import ConfigurationError, NotFoundError
from prophetovol.core.types import OptionType
from prophetovol.reference.settlement import PmIndexClose, intrinsic_value, settlement_source_for
from prophetovol.registry.catalog import SETTLEMENT_SOURCES, all_registries, get_registry
from prophetovol.registry.mechanism import Registry


class Params(BaseModel):
    days: float = Field(description="Calendar days.")


class Undocumented(BaseModel):
    days: float


def make() -> Registry:
    return Registry("test_kind", "Things for tests.")


class TestMechanism:
    def test_register_get_describe(self):
        reg = make()

        @reg.register("b_thing", description="Second.", params=Params, version="2")
        def b_thing():
            pass

        reg.register("a_thing", description="First.", params=Params, version="1")(object)
        assert reg.names() == ["a_thing", "b_thing"]
        assert reg.get("b_thing").target is b_thing and reg.get("b_thing").version == "2"
        info = reg.describe("a_thing")
        assert info.kind == "test_kind" and info.description == "First."
        assert info.params_schema["properties"]["days"]["description"] == "Calendar days."
        assert reg.info().implementations == ["a_thing", "b_thing"]

    def test_unknown_name_lists_known_names(self):
        reg = make()
        reg.register("a_thing", description="First.", params=Params, version="1")(object)
        with pytest.raises(NotFoundError, match=r"no test_kind named 'nope' \(known: a_thing\)"):
            reg.get("nope")

    @pytest.mark.parametrize("name, kwargs, message", [
        ("Bad-Name", {}, "lower snake case"),
        ("ok", {"description": "  "}, "description is required"),
        ("ok", {"version": ""}, "version is required"),
        ("ok", {"params": Undocumented}, "parameters without a description: \\['days'\\]"),
    ])
    def test_registration_rules(self, name, kwargs, message):
        args = {"description": "Desc.", "params": Params, "version": "1"} | kwargs
        with pytest.raises(ConfigurationError, match=message):
            make().register(name, **args)

    def test_duplicate_name_rejected(self):
        reg = make()
        reg.register("a_thing", description="First.", params=Params, version="1")(object)
        with pytest.raises(ConfigurationError, match="already registered"):
            reg.register("a_thing", description="Again.", params=Params, version="1")

    def test_registry_name_must_be_snake_case(self):
        with pytest.raises(ConfigurationError):
            Registry("Bad Kind", "x")


class TestCatalog:
    def test_settlement_sources_listed_with_builtins(self):
        kinds = [r.kind for r in all_registries()]
        assert "settlement_source" in kinds
        assert get_registry("settlement_source").names() == ["pm_index_close"]
        assert SETTLEMENT_SOURCES.describe("pm_index_close").params_schema["type"] == "object"

    def test_unknown_registry(self):
        with pytest.raises(NotFoundError, match="no registry named 'nope'"):
            get_registry("nope")


class TestSettlement:
    @pytest.mark.parametrize("option_type, strike, level, value", [
        (OptionType.CALL, 5000, 5100, 100), (OptionType.CALL, 5000, 4900, 0),
        (OptionType.PUT, 5000, 4900, 100), (OptionType.PUT, 5000, 5100, 0), ("call", 5000, 5000, 0),
    ])
    def test_intrinsic_value(self, option_type, strike, level, value):
        assert intrinsic_value(option_type, strike, level) == value

    def test_pm_contracts_settle_at_the_index_close(self):
        source = settlement_source_for("PM")
        assert isinstance(source, PmIndexClose)
        assert source.settlement_value(OptionType.PUT, 5650.0, 5648.4) == pytest.approx(1.6)

    def test_am_contracts_have_no_source(self):
        with pytest.raises(ConfigurationError, match="no settlement source for AM-settled contracts"):
            settlement_source_for("AM")

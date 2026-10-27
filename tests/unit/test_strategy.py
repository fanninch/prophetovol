"""Strategy specs: model, registries, dry-run validation, YAML/JSON round trip and publishing (TEST-8)."""

from __future__ import annotations

import copy
import json
from typing import get_args

import pytest

from prophetovol.core.context import CallContext
from prophetovol.core.errors import NotFoundError
from prophetovol.core.ids import content_hash
from prophetovol.core.records import AttemptOutcome
from prophetovol.reference.defaults import default_underlyings
from prophetovol.registry.catalog import (ENTRY_SCHEDULES, EXPIRATION_SELECTORS, HEDGE_RULES, SIZING_METHODS,
                                          STRIKE_SELECTORS, TRIGGER_ACTIONS, TRIGGER_CONDITIONS, all_registries)
from prophetovol.registry.params.hedge import HEDGE_RULE_PARAMS
from prophetovol.registry.params.schedules import ENTRY_SCHEDULE_PARAMS
from prophetovol.registry.params.selection import EXPIRATION_SELECTOR_PARAMS, STRIKE_SELECTOR_PARAMS
from prophetovol.registry.params.sizing import SIZING_METHOD_PARAMS
from prophetovol.registry.params.triggers import TRIGGER_CONDITION_PARAMS
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import canonical_body, example_specs, parse_spec_text, spec_to_yaml
from prophetovol.strategy.model import StrategySpec, Trigger
from prophetovol.strategy.validate import SPEC_52_MESSAGE, SpecInvalid, validate_spec

CTX = CallContext.for_channel("library")
UNDERLYINGS = default_underlyings()
EXAMPLES = example_specs()


def example(spec_id: str = "short_call_hedged") -> dict:
    return copy.deepcopy(EXAMPLES[spec_id])


def check(body: dict):
    report, spec = validate_spec(body, UNDERLYINGS)
    return report, spec


def errors(body: dict) -> list[tuple[str, str]]:
    return [(e.path, e.message) for e in check(body)[0].errors]


def warnings(body: dict) -> list[tuple[str, str]]:
    return [(w.path, w.message) for w in check(body)[0].warnings]


# A spec using every implementation, with defaults left out, for the round trip.
EVERYTHING = {
    "id": "everything",
    "underlying": "SPX",
    "legs": [
        {"id": "a", "option_type": "call", "side": "short", "ratio": 2,
         "expiration": {"selector": "target_days", "days": 30, "min_days": 20, "max_days": 40, "tie_break": "earlier",
                        "filter": {"standard_monthly_only": True, "settlement_styles": ["AM"]}},
         "strike": {"selector": "delta", "target": 0.3, "tolerance": 0.02, "tie_break": "nearer_otm",
                    "on_no_match": "nearest_any"}},
        {"id": "b", "option_type": "put", "side": "long",
         "expiration": {"selector": "trading_days_out", "n": 1, "tolerance": 1, "filter": {"settlement_styles": ["PM"]}},
         "strike": {"selector": "atm"}, "roots": ["SPXW"], "hold_to_expiration": True},
        {"id": "c", "option_type": "call", "side": "long",
         "expiration": {"selector": "nth_expiration", "n": 2, "filter": {"weekdays": ["FRI"], "roots": ["SPXW"]}},
         "strike": {"selector": "forward"}, "roots": ["SPXW"]},
        {"id": "d", "option_type": "put", "side": "short",
         "expiration": {"selector": "same_as_leg", "leg": "a"},
         "strike": {"selector": "same_strike_as", "leg": "a", "tolerance_points": 5}},
        {"id": "e", "option_type": "put", "side": "long",
         "expiration": {"selector": "next_after_leg", "leg": "c"},
         "strike": {"selector": "strike_offset", "leg": "c", "percent": -2.5}, "roots": ["SPXW"]},
    ],
    "entry": {"schedule": "weekdays", "weekdays": ["MON", "WED"], "holiday_shift": "next", "max_open": 2},
    "triggers": [
        {"name": "t1", "scope": "structure", "action": "close", "any_of": [
            {"condition": "structure_pnl_per_unit_at_or_above", "amount": 250},
            {"condition": "structure_pnl_per_unit_at_or_below", "amount": -500},
            {"condition": "trading_days_held_at_least", "days": 10},
            {"condition": "structure_min_days_to_expiry_at_or_below", "days": 1, "unit": "trading_days"}]},
        {"name": "t2", "scope": {"leg": "a"}, "action": "roll", "any_of": [
            {"condition": "leg_abs_delta_above", "leg": "a", "threshold": 0.5},
            {"condition": "leg_abs_delta_below", "leg": "a", "threshold": 0.1},
            {"condition": "leg_days_to_expiry_at_or_below", "leg": "a", "days": 5, "unit": "calendar_days"}]},
    ],
    "expiry_handling": "roll_leg",
    "hedge": {"rule": "band", "lower": -0.05, "upper": 0.05, "target": 0},
    "sizing": {"method": "notional", "notional": 1_000_000},
    "selection": {"min_bid": 0.1, "min_open_interest": 10, "exclude_vendor_flagged": True},
}


class TestRegistries:
    @pytest.mark.parametrize("registry, params, key", [
        (EXPIRATION_SELECTORS, EXPIRATION_SELECTOR_PARAMS, "selector"),
        (STRIKE_SELECTORS, STRIKE_SELECTOR_PARAMS, "selector"),
        (ENTRY_SCHEDULES, ENTRY_SCHEDULE_PARAMS, "schedule"),
        (TRIGGER_CONDITIONS, TRIGGER_CONDITION_PARAMS, "condition"),
        (HEDGE_RULES, HEDGE_RULE_PARAMS, "rule"),
        (SIZING_METHODS, SIZING_METHOD_PARAMS, "method"),
    ])
    def test_spec_unions_match_the_registries(self, registry, params, key):
        all_registries()
        by_tag = {get_args(model.model_fields[key].annotation)[0]: model for model in params}
        assert sorted(by_tag) == registry.names()
        for name, model in by_tag.items():
            assert registry.get(name).params is model and registry.get(name).version == "1"
            assert registry.get(name).target(model.model_validate(
                {key: name} | REQUIRED.get(name, {}))).params is not None

    def test_every_phase_1_implementation_is_registered(self):
        names = {r.kind: r.names() for r in all_registries()}
        assert names["expiration_selector"] == ["next_after_leg", "nth_expiration", "same_as_leg", "target_days",
                                                "trading_days_out"]
        assert names["strike_selector"] == ["atm", "delta", "forward", "same_strike_as", "strike_offset"]
        assert names["entry_schedule"] == ["every_n_trading_days", "once", "weekdays", "when_flat"]
        assert len(names["trigger_condition"]) == 7
        assert names["trigger_action"] == ["close", "roll"] == sorted(get_args(Trigger.model_fields["action"].annotation))
        assert names["hedge_rule"] == ["band", "none"] and names["sizing_method"] == ["contracts", "notional"]
        assert names["fill_model"] == ["cross_spread", "mid", "mid_plus_fraction"] and names["constructor"] == ["rules"]

    def test_schemas_describe_every_parameter(self):
        info = STRIKE_SELECTORS.describe("forward")
        assert "usual strike spacing" in info.params_schema["properties"]["tolerance_points"]["description"]
        assert "calendar_days" in TRIGGER_CONDITIONS.describe("leg_days_to_expiry_at_or_below").params_schema[
            "properties"]["unit"]["description"]
        assert TRIGGER_ACTIONS.describe("roll").description.endswith("The opening side waits until the closing side fills.")


REQUIRED = {"target_days": {"days": 45}, "trading_days_out": {"n": 1}, "nth_expiration": {"n": 1},
            "same_as_leg": {"leg": "x"}, "next_after_leg": {"leg": "x"}, "delta": {"target": 0.25},
            "same_strike_as": {"leg": "x"}, "strike_offset": {"leg": "x", "points": 50},
            "every_n_trading_days": {"n": 5}, "weekdays": {"weekdays": ["MON"]},
            "leg_abs_delta_above": {"leg": "x", "threshold": 0.5}, "leg_abs_delta_below": {"leg": "x", "threshold": 0.1},
            "leg_days_to_expiry_at_or_below": {"leg": "x", "days": 5}, "structure_min_days_to_expiry_at_or_below":
            {"days": 5}, "structure_pnl_per_unit_at_or_above": {"amount": 1}, "structure_pnl_per_unit_at_or_below":
            {"amount": -1}, "trading_days_held_at_least": {"days": 1}, "band": {"lower": 0, "upper": 0, "target": 0},
            "contracts": {"quantity": 1}, "notional": {"notional": 1}}


class TestExamples:
    @pytest.mark.parametrize("spec_id", sorted(EXAMPLES))
    def test_appendix_b_specs_are_valid_without_warnings(self, spec_id):
        report, spec = check(example(spec_id))
        assert report.ok and spec is not None and not report.warnings

    def test_leg_order_puts_referenced_legs_first(self):
        assert check(example("long_butterfly_60d"))[0].leg_order == ["short_call", "short_put", "long_call", "long_put"]
        body = example("long_butterfly_60d")
        body["legs"] = list(reversed(body["legs"]))
        assert check(body)[0].leg_order == ["short_call", "long_put", "long_call", "short_put"]


class TestValidationRules:
    def test_schema_errors_have_spec_paths(self):
        body = example()
        body["legs"][0]["strike"]["target"] = 1.5
        body["sizing"] = {"method": "contracts", "quantity": 0}
        assert [p for p, _ in errors(body)] == ["legs[0].strike.target", "sizing.quantity"]

    def test_unknown_names_list_the_known_ones(self):
        body = example()
        body["legs"][0]["strike"] = {"selector": "deltaa", "target": 0.3}
        body["entry"] = {"schedule": "daily"}
        found = errors(body)
        assert found[0] == ("legs[0].strike", "unknown strike selector 'deltaa' (known: atm, delta, forward, "
                                              "same_strike_as, strike_offset)")
        assert found[1][0] == "entry" and found[1][1].startswith("unknown entry schedule 'daily'")

    def test_missing_selector_name(self):
        body = example()
        body["legs"][0]["expiration"] = {"days": 45}
        assert errors(body) == [("legs[0].expiration", "missing 'selector': name the expiration selector to use")]

    def test_unknown_fields_and_bad_scope(self):
        body = example()
        body["legs"][0]["strike"]["targte"] = 0.3
        body["triggers"][0]["scope"] = "leg"
        paths = [p for p, _ in errors(body)]
        assert "legs[0].strike.targte" in paths and "triggers[0].scope" in paths

    def test_references_must_name_other_existing_legs(self):
        body = example("long_butterfly_60d")
        body["legs"][1]["strike"]["leg"] = "short_cal"
        body["legs"][2]["expiration"]["leg"] = "long_call"
        assert errors(body) == [
            ("legs[1].strike.leg", "no leg named 'short_cal' (legs: short_call, short_put, long_call, long_put)"),
            ("legs[2].expiration.leg", "leg 'long_call' cannot refer to itself")]

    def test_cycle_is_named(self):
        body = example("long_butterfly_60d")
        body["legs"][0]["expiration"] = {"selector": "same_as_leg", "leg": "long_put"}
        assert errors(body) == [("legs", "legs refer to each other in a cycle: short_call -> long_put -> short_call")]

    def test_duplicates_and_trigger_references(self):
        body = example("long_butterfly_60d")
        body["legs"][3]["id"] = "long_call"
        body["triggers"].append(copy.deepcopy(body["triggers"][0]))
        body["triggers"][1]["scope"] = {"leg": "nope"}
        body["triggers"][1]["any_of"] = [{"condition": "leg_abs_delta_above", "leg": "gone", "threshold": 0.5}]
        assert [p for p, _ in errors(body)] == ["legs[3].id", "triggers[1].name", "triggers[1].scope.leg",
                                                "triggers[1].any_of[0].leg"]

    @pytest.mark.parametrize("band, ok", [((0, 0, 0), True), ((0, 0.08, 0.03), True), ((0, 0.08, 0.1), False),
                                          ((0.1, 0.0, 0.05), False)])
    def test_band_bounds(self, band, ok):
        body = example()
        body["hedge"] = {"rule": "band", "lower": band[0], "upper": band[1], "target": band[2]}
        found = errors(body)
        assert (not found) is ok
        if not ok:
            assert found[0][0] == "hedge" and "lower <= target <= upper" in found[0][1]

    def test_underlying_and_roots(self):
        body = example()
        body["underlying"] = "NDX"
        assert errors(body) == [("underlying", "unknown underlying 'NDX' (known: SPX)")]
        body = example()
        body["legs"][0]["roots"] = ["SPXQ"]
        body["legs"][0]["expiration"]["filter"] = {"roots": ["JXA"]}
        assert [p for p, _ in errors(body)] == ["legs[0].roots", "legs[0].expiration.filter.roots"]

    def test_target_days_window_and_strike_offset(self):
        body = example()
        body["legs"][0]["expiration"] = {"selector": "target_days", "days": 45, "min_days": 50, "max_days": 40}
        assert "min_days (50) is above max_days (40)" in errors(body)[0][1]
        body = example("long_butterfly_60d")
        body["legs"][2]["strike"] = {"selector": "strike_offset", "leg": "short_call", "points": 50, "percent": 1}
        assert errors(body) == [("legs[2].strike", "give exactly one of points and percent")]

    def test_stop_amount_must_not_be_positive(self):
        body = example()
        body["triggers"][0]["any_of"] = [{"condition": "structure_pnl_per_unit_at_or_below", "amount": 100}]
        assert errors(body)[0][0] == "triggers[0].any_of[0].amount"


class TestExpiryRules:
    def test_spec_52_rejects_holding_am_roots(self):
        body = example()
        body["legs"][0]["hold_to_expiration"] = True
        assert errors(body) == [("legs[0].hold_to_expiration", SPEC_52_MESSAGE)]

    @pytest.mark.parametrize("restriction", [{"roots": ["SPXW"]},
                                             {"expiration": {"selector": "target_days", "days": 45,
                                                             "filter": {"settlement_styles": ["PM"]}}},
                                             {"expiration": {"selector": "target_days", "days": 45,
                                                             "filter": {"roots": ["SPXW"]}}}])
    def test_pm_only_legs_may_be_held(self, restriction):
        body = example()
        body["legs"][0] |= restriction | {"hold_to_expiration": True}
        assert not errors(body)

    def test_same_as_leg_inherits_the_referenced_legs_restriction(self):
        body = example("long_butterfly_60d")
        body["legs"][0]["roots"] = ["SPXW"]
        body["legs"][1]["hold_to_expiration"] = True
        assert not errors(body)
        body["legs"][0]["roots"] = None
        assert errors(body) == [("legs[1].hold_to_expiration", SPEC_52_MESSAGE)]

    def test_spec_53_warns_when_nothing_closes_an_am_leg_in_time(self):
        body = example()
        body["triggers"][0]["any_of"] = body["triggers"][0]["any_of"][:2]
        found = warnings(body)
        assert len(found) == 1 and found[0][0] == "legs[0]"
        assert "force-close it on its last trading day" in found[0][1] and "long weekend" in found[0][1]

    @pytest.mark.parametrize("condition, warns", [
        ({"condition": "leg_days_to_expiry_at_or_below", "leg": "short_call", "days": 1, "unit": "trading_days"}, False),
        ({"condition": "leg_days_to_expiry_at_or_below", "leg": "short_call", "days": 1, "unit": "calendar_days"}, False),
        ({"condition": "leg_days_to_expiry_at_or_below", "leg": "short_call", "days": 0.5, "unit": "calendar_days"}, True),
        ({"condition": "structure_min_days_to_expiry_at_or_below", "days": 2, "unit": "trading_days"}, False),
        ({"condition": "trading_days_held_at_least", "days": 30}, True),
    ])
    def test_spec_53_qualifying_conditions(self, condition, warns):
        body = example()
        body["triggers"] = [{"name": "t", "scope": "structure", "action": "close", "any_of": [condition]}]
        assert bool(warnings(body)) is warns

    def test_spec_53_structure_trigger_on_an_earlier_leg_covers_a_later_one(self):
        assert not warnings(example("put_diagonal_banded"))  # long put (65–85 days) outlives the short (35–55)
        body = example("put_diagonal_banded")
        body["legs"][1]["expiration"]["days"] = 50  # windows overlap: the long put may expire first
        assert [p for p, _ in warnings(body)] == ["legs[1]"]

    def test_leg_trigger_on_another_leg_does_not_cover(self):
        body = example("put_diagonal_banded")
        body["triggers"][0]["scope"] = {"leg": "short_put"}
        assert [p for p, _ in warnings(body)] == ["legs[1]"]

    def test_unit_left_out_warns(self):
        body = example()
        del body["triggers"][0]["any_of"][2]["unit"]
        report, spec = check(body)
        assert report.ok and spec.triggers[0].any_of[2].unit == "calendar_days"
        assert [(w.path, w.message) for w in report.warnings] == [
            ("triggers[0].any_of[2].unit", "unit not stated; calendar_days assumed. State unit: calendar_days or "
                                           "unit: trading_days.")]


class TestRoundTrip:
    @pytest.mark.parametrize("body", [*(example(s) for s in sorted(EXAMPLES)), EVERYTHING], ids=lambda b: b["id"])
    def test_export_reimports_to_the_same_canonical_form_and_hash(self, body):
        report, spec = check(copy.deepcopy(body))
        assert report.ok, report.errors
        canonical = canonical_body(spec)
        text = spec_to_yaml(canonical)
        again = canonical_body(check(parse_spec_text(text, "spec.yaml"))[1])
        assert again == canonical and content_hash(again) == content_hash(canonical)
        assert spec_to_yaml(again) == text

    def test_yaml_and_json_import_are_equal(self):
        as_json = parse_spec_text(json.dumps(EVERYTHING), "spec.json")
        assert canonical_body(check(as_json)[1]) == canonical_body(check(copy.deepcopy(EVERYTHING))[1])

    def test_scope_is_written_as_in_specs(self):
        body = canonical_body(check(copy.deepcopy(EVERYTHING))[1])
        assert [t["scope"] for t in body["triggers"]] == ["structure", {"leg": "a"}]
        assert body["legs"][0]["expiration"]["filter"]["settlement_styles"] == ["AM"]

    def test_export_states_every_default(self):
        body = canonical_body(StrategySpec.model_validate(example()))
        assert body["hedge"]["rule"] == "band" and body["selection"] == {
            "require_valid_quote": True, "min_bid": 0.05, "min_open_interest": 0, "exclude_vendor_flagged": False}
        assert body["legs"][0]["strike"]["tolerance"] == 0.05 and body["entry"]["cooldown_trading_days"] == 1

    def test_invalid_yaml(self):
        with pytest.raises(Exception, match="not valid YAML"):
            parse_spec_text("legs: [unclosed", "x.yaml")


class TestPublishing:
    def test_publish_versions_and_unchanged_content(self, tmp_path):
        with BacktestService.open(tmp_path / "home") as svc:
            first = svc.publish_spec(example(), CTX)
            assert first.created and first.definition.version == 1
            again = svc.publish_spec(example(), CTX)
            assert not again.created and again.definition.version == 1
            changed = example()
            changed["sizing"]["quantity"] = 5
            second = svc.publish_spec(changed, CTX)
            assert second.created and second.definition.version == 2
            assert second.definition.content_hash == content_hash(second.definition.body)
            assert svc.get_spec("short_call_hedged", 1).sizing.quantity == 10
            assert svc.get_spec("short_call_hedged").sizing.quantity == 5
            assert [v.version for v in svc.spec_versions("short_call_hedged")] == [1, 2]
            assert [d.key for d in svc.list_specs()] == ["short_call_hedged"]
            assert second.definition.actor == CTX.actor and second.definition.channel == CTX.channel

    def test_defaults_left_out_or_stated_publish_the_same_version(self, tmp_path):
        with BacktestService.open(tmp_path / "home") as svc:
            svc.publish_spec(example(), CTX)
            exported = parse_spec_text(svc.export_spec("short_call_hedged"), "x.yaml")
            assert not svc.publish_spec(exported, CTX).created
            assert svc.export_spec("short_call_hedged").startswith("id: short_call_hedged\n")

    def test_invalid_specs_are_refused_and_audited(self, tmp_path):
        body = example()
        body["legs"][0]["hold_to_expiration"] = True
        with BacktestService.open(tmp_path / "home") as svc:
            with pytest.raises(SpecInvalid) as caught:
                svc.publish_spec(body, CTX)
            assert caught.value.report.errors[0].message == SPEC_52_MESSAGE
            with pytest.raises(SpecInvalid):
                svc.validate_spec(body, CTX)
            assert svc.validate_spec(example(), CTX).ok
            attempts = svc.page_attempts().items
            assert [(a.operation, a.outcome) for a in attempts[:3]] == [
                ("spec.validate", AttemptOutcome.OK), ("spec.validate", AttemptOutcome.REJECTED),
                ("spec.publish", AttemptOutcome.REJECTED)]
            assert SPEC_52_MESSAGE in attempts[2].reasons[0]
            assert svc.list_specs() == []

    def test_unknown_spec_and_version(self, tmp_path):
        with BacktestService.open(tmp_path / "home") as svc:
            with pytest.raises(NotFoundError, match="no strategy_spec named 'nope'"):
                svc.get_spec("nope")
            with pytest.raises(NotFoundError, match="no spec named 'nope'"):
                svc.spec_versions("nope")
            svc.publish_spec(example(), CTX)
            with pytest.raises(NotFoundError, match="has no version 3"):
                svc.export_spec("short_call_hedged", 3)

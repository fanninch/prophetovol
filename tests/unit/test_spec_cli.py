"""The ``prophetovol spec`` commands (INT-40, SPEC-80, SPEC-81)."""

from __future__ import annotations

import io
import json
import sys

import yaml
from click.testing import CliRunner

from prophetovol.cli import _tolerant_output, main
from prophetovol.strategy.io import example_spec_texts


def invoke(home, *args, input=None):
    return CliRunner().invoke(main, ["--home", str(home), *map(str, args)], input=input)


def write_examples(tmp_path):
    folder = tmp_path / "specs"
    result = invoke(tmp_path / "home", "spec", "examples", "--out", folder)
    assert result.exit_code == 0, result.output
    return folder


def test_examples_are_listed_and_written(tmp_path):
    listed = invoke(tmp_path / "home", "spec", "examples")
    assert listed.exit_code == 0 and "put_diagonal_banded.yaml" in listed.output
    folder = write_examples(tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == sorted(example_spec_texts())
    again = invoke(tmp_path / "home", "spec", "examples", "--out", folder)
    assert again.exit_code != 0 and "use --force" in again.output
    assert invoke(tmp_path / "home", "spec", "examples", "--out", folder, "--force").exit_code == 0


def test_validate_publish_list_show_export(tmp_path):
    home, folder = tmp_path / "home", write_examples(tmp_path)
    valid = invoke(home, "spec", "validate", folder / "long_butterfly_60d.yaml")
    assert valid.exit_code == 0 and "Valid: long_butterfly_60d, 0 warnings." in valid.output
    assert "selected in this order: short_call, short_put, long_call, long_put." in valid.output
    published = invoke(home, "spec", "publish", folder / "long_butterfly_60d.yaml")
    assert published.exit_code == 0 and "Published long_butterfly_60d version 1 (hash " in published.output
    unchanged = invoke(home, "spec", "publish", folder / "long_butterfly_60d.yaml")
    assert "Unchanged: long_butterfly_60d version 1 already has this content; nothing published." in unchanged.output

    doc = yaml.safe_load((folder / "long_butterfly_60d.yaml").read_text(encoding="utf-8"))
    doc["sizing"]["quantity"] = 4
    del doc["triggers"][0]["any_of"][0]["unit"]
    as_json = tmp_path / "v2.json"
    as_json.write_text(json.dumps(doc), encoding="utf-8")
    second = invoke(home, "spec", "publish", as_json)
    assert second.exit_code == 0 and "version 2" in second.output
    assert ["warning", "triggers[0].any_of[0].unit", "unit", "not", "stated;"] == second.output.splitlines()[2].split()[:5]

    listing = invoke(home, "spec", "list")
    assert listing.exit_code == 0 and "long_butterfly_60d  2" in listing.output and "1 spec." in listing.output
    shown = invoke(home, "spec", "show", "long_butterfly_60d@1", "--versions")
    assert shown.exit_code == 0 and "Spec: long_butterfly_60d version 1 of 2" in shown.output
    assert "quantity: 10.0" in shown.output and "\n2        " in shown.output
    exported = invoke(home, "spec", "export", "long_butterfly_60d")
    assert exported.exit_code == 0 and exported.output.startswith("id: long_butterfly_60d\n")
    out = tmp_path / "exported.yaml"
    assert invoke(home, "spec", "export", "long_butterfly_60d@2", "--out", out).exit_code == 0
    assert "Unchanged" in invoke(home, "spec", "publish", out).output


def test_invalid_spec_lists_every_finding_and_fails(tmp_path):
    home, folder = tmp_path / "home", write_examples(tmp_path)
    doc = yaml.safe_load((folder / "long_butterfly_60d.yaml").read_text(encoding="utf-8"))
    doc["legs"][1]["strike"]["leg"] = "short_cal"
    doc["legs"][2]["hold_to_expiration"] = True
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(doc), encoding="utf-8")
    result = invoke(home, "spec", "validate", bad)
    assert result.exit_code != 0 and "Traceback" not in result.output
    assert any(line.split()[:2] == ["error", "legs[1].strike.leg"] and "no leg named 'short_cal'" in line
               for line in result.output.splitlines())
    assert "long_butterfly_60d is not valid: 1 error, 0 warnings." in result.output
    refused = invoke(home, "spec", "publish", bad)
    assert refused.exit_code != 0 and "long_butterfly_60d was not published: 1 error." in refused.output
    assert "0 specs." in invoke(home, "spec", "list").output


def test_readable_errors(tmp_path):
    home = tmp_path / "home"
    broken = tmp_path / "broken.yaml"
    broken.write_text("legs: [unclosed", encoding="utf-8")
    for args, message in [
        (("spec", "validate", broken), "broken.yaml is not valid YAML"),
        (("spec", "validate", tmp_path / "missing.yaml"), "cannot read"),
        (("spec", "show", "nope"), "no strategy_spec named 'nope'"),
        (("spec", "show", "nope@x"), "is not <id> or <id>@<version>"),
    ]:
        result = invoke(home, *args)
        assert result.exit_code != 0 and message in result.output and "Traceback" not in result.output, result.output


def test_output_that_cannot_encode_a_character_replaces_it(monkeypatch):
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    _tolerant_output()
    stream.write("lower ≤ target")
    stream.flush()
    assert buffer.getvalue() == b"lower ? target"

"""Specs as YAML and JSON (SPEC-81), and the shipped examples (SPEC-82).

Import accepts YAML or JSON. Export writes a spec's **canonical form**: every field in model order,
defaults stated, as YAML that import accepts. Importing an export gives the same canonical JSON and
so the same content hash (VER-2): the round trip is exact.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from prophetovol.core.errors import ValidationFailed, ValidationIssue
from prophetovol.strategy.model import StrategySpec


def parse_spec_text(text: str, name: str = "") -> Any:
    """Parse a spec file's text: JSON when the name ends in ``.json``, YAML otherwise.

    :param text: The file's contents.
    :param name: The file's name, used to choose the format and in messages.
    :returns: The parsed data (not yet validated).
    :raises ValidationFailed: If the text is not valid YAML or JSON.
    """
    try:
        if name.lower().endswith(".json"):
            return json.loads(text)
        return yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        kind = "JSON" if name.lower().endswith(".json") else "YAML"
        raise ValidationFailed([ValidationIssue("", f"{name or 'the spec'} is not valid {kind}: {exc}")]) from None


def read_spec_file(path: Path | str) -> Any:
    """Read and parse a spec file (YAML, or JSON for ``.json``).

    :param path: The file.
    :returns: The parsed data (not yet validated).
    :raises ValidationFailed: If the file cannot be read or parsed.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationFailed([ValidationIssue("", f"cannot read {path}: {exc.strerror or exc}")]) from None
    return parse_spec_text(text, path.name)


def canonical_body(spec: StrategySpec) -> dict[str, Any]:
    """The spec's canonical JSON-compatible form: what is stored and hashed when it is published.

    :param spec: A validated spec.
    :returns: Every field in model order, defaults stated.
    """
    return spec.model_dump(mode="json")


def spec_to_yaml(body: dict[str, Any]) -> str:
    """Write a canonical spec body as YAML that import accepts.

    :param body: A canonical body, from :func:`canonical_body` or a stored version.
    :returns: The YAML text, keys in model order.
    """
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


def example_specs() -> dict[str, dict[str, Any]]:
    """The Appendix B example specs shipped with the package (SPEC-82), parsed.

    :returns: The examples keyed by spec id, in file-name order.
    """
    base = resources.files("prophetovol.strategy") / "examples"
    files = sorted((f for f in base.iterdir() if f.name.endswith(".yaml")), key=lambda f: f.name)
    docs = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]
    return {doc["id"]: doc for doc in docs}


def example_spec_texts() -> dict[str, str]:
    """The example spec files' text, as shipped, keyed by file name.

    :returns: File names mapped to their YAML text.
    """
    base = resources.files("prophetovol.strategy") / "examples"
    return {f.name: f.read_text(encoding="utf-8") for f in sorted(base.iterdir(), key=lambda f: f.name)
            if f.name.endswith(".yaml")}

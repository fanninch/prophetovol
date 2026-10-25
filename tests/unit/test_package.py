"""The package installs, imports, and reports one version."""

import importlib
import pkgutil
from importlib import metadata

import prophetovol

SUBPACKAGES = ["core", "registry", "registry.params", "reference", "storage", "storage.duckdb", "data",
               "pricing", "engine", "stress", "results", "runs", "server", "cli", "testdata"]


def test_version_is_single_sourced():
    assert prophetovol.__version__ == metadata.version("prophetovol") == "0.1.0"


def test_every_planned_subpackage_imports():
    for name in SUBPACKAGES:
        importlib.import_module(f"prophetovol.{name}")


def test_every_module_imports():
    names = [m.name for m in pkgutil.walk_packages(prophetovol.__path__, "prophetovol.")]
    assert names
    for name in names:
        importlib.import_module(name)


def test_console_script_is_declared():
    scripts = {ep.name: ep.value for ep in metadata.entry_points(group="console_scripts")}
    assert scripts.get("prophetovol") == "prophetovol.cli:main"

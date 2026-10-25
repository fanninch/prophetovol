# ProphetoVol

Deterministic backtesting of index options on end-of-day vendor data (ivolatility format):
versioned data and strategies, a point-in-time engine, stress tests and statistics, with a
CLI and, later, a local browser GUI.

**Status:** Phase 1 in progress. The requirements and the implementation plan are in
[`specs/`](specs/README.md). This README grows as features land; install, the demo, importing
data, publishing a spec and running a backtest are added as those phases are built.

## Install

Python 3.11 or later (developed on 3.12). From the repository's root folder, in a virtual
environment:

```bash
pip install -r build_requirements.txt
```

This installs the package in editable mode with the tools to test and build it.
`requirements.txt` installs only what ships. Dependencies are declared once, in
`pyproject.toml`.

```bash
prophetovol --version
```

## Home directory

ProphetoVol keeps its catalog, results and market data in a home directory, chosen in this order:
`--home DIR`, then the `PROPHETOVOL_HOME` environment variable, then `~/.prophetovol`.

## Tests

```bash
pytest
```

Optional tests against real vendor files run only when `PROPHETOVOL_VENDOR_DATA` names a folder
with one subfolder per underlying (for example `spx/`). Vendor data is licensed and never goes in
the repository.

## Building a wheel

```bash
python -m build --wheel
```

The wheel is pure Python (`py3-none-any`).

## Layout

| Path | Contents |
| --- | --- |
| `src/prophetovol/` | the package: `core`, `registry`, `reference`, `storage`, `data`, `pricing`, `engine`, `stress`, `results`, `runs`, `server`, `cli`, `testdata` |
| `tests/` | `unit/`, `meta/` (documentation rules), `packaging/` (the wheel) |
| `specs/` | roadmap, requirements and implementation plans |

Docstrings are reStructuredText with Sphinx field lists (`:param:`, `:returns:`, `:raises:`), so a
Sphinx site can be built later.

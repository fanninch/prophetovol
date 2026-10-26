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
`--home DIR`, then the `PROPHETOVOL_HOME` environment variable, then `~/.prophetovol`. It is
created on first use:

| Path | Contents |
| --- | --- |
| `catalog.duckdb` | reference data and other versioned definitions, imports, data versions, jobs, attempts |
| `results.duckdb` | run output |
| `market/underlying=<U>/year=<YYYY>/month=<MM>/<import_id>.parquet` | market snapshots, one file per import per month |
| `uploads/`, `logs/` | files being ingested; the server log |

Only one process can open a home directory at a time (for example, the CLI cannot use it while
`prophetovol serve` is running); a second process gets a message saying so. The first open
publishes the shipped reference data as version 1; later changes to it are never overwritten.

## Reference data and conventions

The package ships the SPX underlying and the `ivolatility_eod` data source as YAML
(`src/prophetovol/reference/defaults/`). SPX lists every option root found in the vendor files
since 2007, each mapped to its settlement style and to one of today's two roots: `SPX` (AM-settled)
or `SPXW` (PM-settled). A root that is not listed fails ingest rather than being guessed.

Time to expiry follows the vendor's convention: calendar minutes on the exchange clock (daylight
saving ignored) over the minutes in 365 days. An expiration dated on a non-trading day (the
Saturday-dated monthlies before 2015) settles on the trading day before it; AM-settled contracts
last trade the trading day before they settle. The full list of conventions is in
`prophetovol.core.conventions`.

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
| `tests/` | `unit/`, `contract/` (the storage adapter contract suite), `meta/` (documentation rules), `packaging/` (the wheel) |
| `specs/` | roadmap, requirements and implementation plans |

Docstrings are reStructuredText with Sphinx field lists (`:param:`, `:returns:`, `:raises:`), so a
Sphinx site can be built later.

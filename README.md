# ProphetoVol

Deterministic backtesting of index options on end-of-day vendor data (ivolatility format):
versioned data and strategies, a point-in-time engine, stress tests and statistics, with a
CLI and, later, a local browser GUI.

**Status:** Phase 1 is being built: plan phases 0–5 of 24 are done (repository foundation, conventions and calendar,
storage and catalog, jobs and audit, synthetic data); milestone M1 (data foundation) is in progress. The requirements, the
implementation plan and the [requirement status tracker](specs/implementation_plans/ProphetoVol%20—%20Phase%201%20Requirement%20Status.md)
are in [`specs/`](specs/README.md). This README grows as features land; install, the demo, importing
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

## Synthetic test data

`prophetovol testdata generate` writes option files in the vendor's exact 22-column format for a
synthetic SPX-like index, so everything can be tried and tested without licensed vendor data:

```bash
prophetovol testdata generate --out sample_data --start 2024-03-01 --end 2024-03-28
```

`--conventions older` reproduces the vendor's older files instead (five-character option codes,
historical roots, Saturday-dated monthlies, one underlying price per date, discounted deltas);
`--rows-per-file` splits the output into several files, as the vendor's downloads are; `--seed`
changes the random path (the same seed always gives the same files).

## Jobs and the attempts log

Long operations (imports, commits, purges, runs) run as jobs, recorded in the catalog with their
progress, so job history survives a restart. The server runs them one at a time in the
background; the CLI runs them in the foreground and records them the same way. A job left
unfinished by a process that stopped is marked failed ("interrupted") the next time the home
directory is opened.

Every requested operation is recorded in the attempts log with who asked, through which client,
and the outcome: `ok`, `rejected` (with the reasons, for example each validation error and its
field), or `error`. Attempts are never deleted.

## Reference data and conventions

The package ships the SPX underlying and the `ivolatility_eod` data source as YAML
(`src/prophetovol/reference/defaults/`). SPX lists every option root found in the vendor files
since 2007, each mapped to its settlement style and to one of today's two roots: `SPX` (AM-settled)
or `SPXW` (PM-settled). A root that is not listed fails ingest rather than being guessed.

ProphetoVol has its own conventions for time, prices, implied vol and greeks, independent of any
data vendor; each data source's ingest converts its files into them and keeps the vendor's original
values alongside. Time to expiry is calendar minutes on the exchange clock (daylight saving ignored)
over the minutes in 365 days. Delta is the undiscounted Black-76 forward delta (call minus put delta
is exactly 1), vega is per volatility point and theta per calendar day. An expiration dated on a non-trading day (the
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

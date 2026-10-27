# ProphetoVol

Deterministic backtesting of index options on end-of-day vendor data (ivolatility format):
versioned data and strategies, a point-in-time engine, stress tests and statistics, with a
CLI and, later, a local browser GUI.

**Status:** Phase 1 is being built. Plan phases 0–11 of 24 are done. Milestone M1 (data foundation)
is complete, including its checkpoint demo on real data: data import, review, commit, delete, purge
and coverage through the `prophetovol` CLI. M2 (engine core) has begun: strategy specs (validation,
publishing, YAML round trips), run configurations, pre-flight checks, and the engine's contract
selection and entry schedules. The requirements, the implementation plan and the
[requirement status tracker](specs/implementation_plans/ProphetoVol%20—%20Phase%201%20Requirement%20Status.md)
are in [`specs/`](specs/README.md). Strategies, runs, stress, statistics and the GUI follow in
milestones M2 to M4.

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

## Importing data

Vendor files are imported as one import per command: CSV files, folders of them, or zip archives
(a year of SPX normally comes as several files). Each import is validated, with a quality report
kept permanently, normalized into ProphetoVol's own conventions with the vendor's original values
kept alongside, and staged. You then review it and choose what becomes active:

```bash
prophetovol data import D:/vendor/spx/spx_2023
```

The command shows the quality report and the overlap with data already active, then asks for a
commit choice:

- `replace`: every incoming snapshot becomes active; replaced versions are kept as superseded.
- `add-new`: only dates without active data become active; overlapping incoming versions are
  kept as superseded, and can be purged.
- `cancel`: the staged import is discarded (also what happens on Ctrl+C or end of input).

`--commit replace` or `--commit add-new` skips the question, for scripts. A failed validation
exits with an error and keeps the import and its report for review.

## Reviewing and managing data

```bash
prophetovol data list                                # imports, newest first, including failed and discarded ones
prophetovol data quality IMPORT_ID [--details|--json] # the stored quality report; --details adds dates and examples
prophetovol data coverage [--underlying SPX] [--from 2024-01-01 --to 2024-12-31] [--daily]
prophetovol data delete --underlying SPX --from 2024-01-01 --to 2024-01-31
prophetovol data purge --import-id IMPORT_ID         # or --underlying SPX --from ... --to ...
```

`data list` shows each import's rows and dates as imported, and in *Active days* how many of its
snapshots are active now, after later replacements, deletes and purges. Coverage summarizes trading
days by month (covered, missing, non-trading dates with data, contracts and flagged days), with
each run of months without data on one line; `--daily` lists each day with its import and quality
flags. `--json` prints the complete quality report for scripts.

**Delete** deactivates active data in a date range but keeps the files. **Purge** removes only
superseded or deleted versions and reclaims disk space, rewriting a monthly file when it also
holds data that must remain (it needs temporary disk space for backups). Both show an exact
preview, including any runs that read the data, and change nothing until you confirm (`--yes`
confirms for scripts). Affected runs keep their results and are flagged *data superseded*.
Interrupted file changes are recovered when the home is next opened.

Other commands:

```bash
prophetovol registry list [TYPE]          # component types, or the implementations of one type
prophetovol registry show TYPE NAME       # an implementation with its full parameter schema
prophetovol jobs list [--status running]  # persisted jobs, newest first
prophetovol jobs show JOB_ID
prophetovol docs generate [--check]       # regenerate (or check) docs/reference from the schemas
```

Expected errors are shown as short messages; unexpected ones say only that details were written
to `logs/server.log` in the home directory. Every command is also a `BacktestService` operation
(`import_files`, `overlap`, `commit_import`, `coverage`, `preview_data_change`, `delete_data`,
`purge_data`, …) for use from Python; commit, delete and purge return persisted jobs and accept
`background=True` when the job runner is running.

## Strategy specs

A strategy spec defines a structure's legs (each with an expiration selector and a strike
selector), when structures open, the triggers that close or roll them, what happens at expiry,
hedging and sizing. Specs are YAML or JSON files; the three examples of the requirements'
Appendix B ship with the package:

```bash
prophetovol spec examples --out my_specs                 # write the example specs to a folder
prophetovol spec validate my_specs/short_call_hedged.yaml  # dry run: every error and warning, nothing published
prophetovol spec publish my_specs/short_call_hedged.yaml   # publish version 1 (unchanged content publishes nothing)
prophetovol spec list
prophetovol spec show short_call_hedged@1 [--versions]
prophetovol spec export short_call_hedged [--out FILE]     # YAML that publishes back to the same version
```

Validation reports each problem with its field path, for example `legs[1].strike.leg`. It
rejects holding AM-settled legs to expiration (SPEC-52), and warns when an AM-settled leg has no
trigger closing it at least one trading day before expiry, since the engine then force-closes it
on its last trading day (SPEC-53). Published versions are immutable and hashed; every change
publishes a new version. `prophetovol registry list` and `registry show` describe every selector,
schedule, condition, hedge rule and sizing method with its parameters. Runs arrive in Phase 14.

Until the `run` commands arrive, a run's **pre-flight check** is available from Python. It reports
every problem at once (spec, configuration, missing trading days, empty snapshots) and fixes the
run's steps:

```python
from prophetovol.core.context import CallContext
from prophetovol.runs.service import BacktestService

with BacktestService.open() as svc:
    report = svc.preflight_run("short_call_hedged", {"start_date": "2024-04-11", "end_date": "2024-06-24",
                                                     "capital": 1_000_000}, CallContext.for_channel("library"))
    print(len(report.schedule.steps), "steps;", [w.message for w in report.warnings])
```

A failed check raises `PreflightFailed`, whose `report` lists the errors and warnings. Missing days
block a run unless the configuration sets `allow_missing_days: true`. Configurations can be saved
as named, versioned templates with `save_run_template`.

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
over the minutes in 365 days. Delta is the undiscounted Black-76 forward delta (at the same strike and
implied vol, call minus put delta is exactly 1), vega is per volatility point and theta per calendar
day. An expiration dated on a non-trading day (the
Saturday-dated monthlies before 2015) settles on the trading day before it; AM-settled contracts
last trade the trading day before they settle. The full list of conventions is in
`prophetovol.core.conventions`.

## Tests

```bash
pytest
```

Optional tests against real vendor files (`tests/realdata/`, marked `realdata`) run only when
`PROPHETOVOL_VENDOR_DATA` names a folder with one subfolder per underlying, holding `spx/spx_2008`
and `spx/spx_2023`. They import both years through the CLI and walk through checkpoint 1 (quality,
overlap, commit, coverage, delete and purge) in a temporary home. Vendor data is licensed and never
goes in the repository.

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
| `scripts/` | developer tools: `update_tracker.py` updates and checks the requirement status tracker |
| `CLAUDE.md`, `.claude/` | guidance and settings for Claude Code (see below) |
| `specs/` | roadmap, requirements and implementation plans |

Docstrings are reStructuredText with Sphinx field lists (`:param:`, `:returns:`, `:raises:`), so a
Sphinx site can be built later.

## Working with Claude Code

`CLAUDE.md` gives Claude Code the project's process, architecture rules, code style, commands and
known pitfalls; it is read automatically at the start of every session. `.claude/settings.json`
denies history-changing git commands (the project owner does all git operations) and allows the
routine test and build commands. The `phase-wrapup` skill (`.claude/skills/phase-wrapup/`) is the
checklist that ends every portion of work: suites green, plan notes, the requirement status tracker,
status lines, and a commit message. Personal overrides go in `.claude/settings.local.json`, which git
ignores.

# ProphetoVol: guidance for Claude Code

ProphetoVol is a deterministic backtester for index options on end-of-day vendor data. Phase 1 is being
built from agreed specifications; read them before changing behaviour.

## Where things are

- `specs/requirements/ProphetoVol — Phase 1 Requirements Specification.md`: **the authority** on what to build. Requirement IDs (DATA-13, CONV-10, …) are used in code, tests and docs.
- `specs/implementation_plans/ProphetoVol — Phase 1 Implementation Plan.md`: design, phases, decisions, risks, Phase 0 findings (§15) and implementation notes (§16).
- `specs/implementation_plans/ProphetoVol — Phase 1 Requirement Status.md`: one row per requirement ID (Done, Partial, Not started); updated in every portion of work.
- `specs/ProphetoVol — Project Roadmap.md`: later phases, context only; nothing there is built until it has agreed requirements.

## Process

- **Requirements, then plan, then phases.** Do not jump from an idea to code. If a requirement is wrong or incomplete, propose a new requirements version and wait for agreement before the code departs from it.
- **Git is the project owner's job.** Never branch, commit, amend, push, merge, rebase, tag, stash or check out; leave changes in the working tree. `.claude/settings.json` denies these commands.
- **Each portion of work ends with the `phase-wrapup` skill:** suites green, plan §16 notes and status line, the requirement status tracker, status lines in `specs/README.md`, the roadmap and `README.md`, and a commit message listing the pieces done.
- Corrections between phases (for example the internal-conventions change) go on their own branch, which the owner creates, with their own note in plan §16.

## Architecture rules

- **`BacktestService` (`runs/service.py`) is the only owner of storage.** The CLI and the API are thin clients; missing capabilities are added to the service.
- **Storage:** writes go through the `StorageAdapter` interface (`storage/adapter.py`); reads are Ibis expressions (DATA-81). Physical layout is known only to the adapter. Every adapter passes `tests/contract/`.
- **The engine is a pure library:** no file, database or network access, no clock, no randomness, no unordered iteration that affects output (ARC-2, ENG-10). It reads market data only through `MarketDataView`, which refuses anything after the step's as-of time (ARC-3).
- **Internal conventions with adapters (§5.4, CONV-10, DATA-15).** ProphetoVol's conventions (time to expiry on the exchange clock, undiscounted forward delta, vega per vol point, theta per calendar day, …) are its own. Vendor-specific code lives only in a data source's ingest adapter (and in `testdata/`, which writes vendor files). Core code (`pricing`, `engine`, `stress`, `core/conventions.py`) never takes vendor-specific parameters. Vendor originals are kept in `vendor_*` columns.
- **Registries** (`registry/`) for every extensible component type; parameter models in `registry/params/`, apart from implementations. Registration enforces a description, a version and documented parameters (REG-2).
- **Jobs** run one at a time (`runs/jobs.py`); each thread uses its own storage cursor (`storage.reader()`); DuckDB connections are not thread-safe.
- **Audit:** service operations that write or can be refused are wrapped with `@audited` and take a `context: CallContext`.
- **Pure Python** (DIST-1): no compilation, no obfuscation. **No shared code with `data_profiler`**; copy and adapt only where it saves time.

## Code style

- Docstrings are **reStructuredText with Sphinx fields** (`:param name:`, `:returns:`, `:raises:`) on every public module, class, function and method. Click commands put reST fields after `\f` so they stay out of `--help`.
- Every pydantic field has a `description` (DOC-1); descriptions state units, signs, defaults and interactions (DOC-2).
- Name time quantities by their units: `days_to_expiry`, `trading_days_to_expiry`, `time_to_expiry_years` (TIME-3).
- Instants are aware UTC `datetime`s in code; exchange clock times are naive local `datetime`s (see `pricing/time.py`).
- `tests/meta/test_documentation.py` enforces the docstring and description rules on the whole package.

## Commands (run from the repository root)

```bash
.venv/Scripts/python.exe -m pytest -q                       # whole suite
.venv/Scripts/python.exe -m pytest -q tests/unit/test_time.py
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-build-isolation --no-index -q -e ".[dev]"
.venv/Scripts/python.exe -m build --wheel --no-isolation
.venv/Scripts/python.exe scripts/update_tracker.py --help    # requirement status tracker
```

- Windows; Python 3.12 in `.venv`; installs are project-local only and recorded in `pyproject.toml` (the one list of dependencies). Ask before installing anything outside the project.
- Pytest markers: `slow` (wheel build), `realdata` (needs vendor files).

## Data

- **Vendor data is licensed and never enters the repository** (INT-52). `PROPHETOVOL_VENDOR_DATA` names a folder outside it with one subfolder per underlying (`spx/`). Tests use synthetic data from `prophetovol testdata generate` (`testdata/generator.py`); real-data tests are optional and marked `realdata`.
- Never print the whole environment to find a variable: it holds secrets. Read only the variable needed.

## Known pitfalls

- DuckDB cursors do not inherit a connection's `TimeZone`, and reading `TIMESTAMPTZ` into Python needs `pytz`: the catalog stores instants as naive UTC `TIMESTAMP` and converts at the edges.
- Read market Parquet with `hive_partitioning=False`: the `underlying=/year=/month=` folders are layout, not columns (DuckDB infers `month` as a string).
- `at` is a reserved word in DuckDB.
- Write market partitions one month at a time: a single sorted write of a year runs out of memory at a 1 GB limit.
- On Good Friday weeks a holiday-shifted weekly can land on a daily's date: keep listings unique per (expiration, root).
- The vendor's `stock price for iv` is one price per date before 2018-06-25 and a per-series forward from then; its greeks before that date are spot-based with discounted deltas (DATA-13, DATA-14).

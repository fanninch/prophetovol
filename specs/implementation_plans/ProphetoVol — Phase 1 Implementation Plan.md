# ProphetoVol — Phase 1 Implementation Plan

Oct 25, 2026 · @Chuck · **Status: Agreed (v3), updated for requirements v6 and Phase 0's findings. Phase 0 done; Phase 1 in progress.** · Implements: *ProphetoVol — Phase 1 Requirements Specification* (v6, agreed), referred to below as "the requirements". IDs such as DATA-31 or ENG-41 refer to that document.

## 1. Approach

- **Correct first.** Every number the tool reports must be reproducible and explainable. Hand-checked golden tests (TEST-1) and the accounting invariants (ENG-33) are written with the code they test, not afterwards.
- **Follow the requirements' milestones.** M1 data foundation → M2 engine core → M3 stress and analytics → M4 server and GUI (requirements §21). Each milestone ends usable on its own, with a demo checkpoint.
- **One milestone in detail at a time.** The design that spans milestones (§4: storage, market data access, the engine and registry interfaces, run output, jobs, audit) is settled now, because M1's storage must serve M2's engine. **M1 is planned in detail** (§6). M2–M4 are planned at phase level (§7–§9), and each is detailed and reviewed with you before it starts, using what the previous milestone taught us.
- **Back end first.** M1–M3 are the service, the engine and the CLI, tested in pytest. The HTTP API and the GUI are M4, as thin clients of the same service (ARC-1).
- **Check before building.** Phase 0 (§5) tests the assumptions the design rests on, above all whether market data can be read fast enough to meet the run-time target (NFR-1), using your real vendor files.
- **Working rhythm.** Each phase ends with every suite green and its implementation notes added to §16. **Changes are left uncommitted**: you do all git operations (branches, commits, pushes). Decisions and deviations are recorded as they happen.
- **No shared code with the data profiler.** Where copying and adapting a profiler module is quicker than writing it (§13, decision 13), it is copied into this repository and becomes ProphetoVol's own code.
- **If a requirement turns out wrong** during implementation, the requirements get a new version, agreed with you, before the code departs from them.

## 2. Technology

### 2.1 Python

As in requirements §16.1, developed and tested on **Python 3.12** (the project's `.venv`, 3.12.2); the package declares `requires-python = ">=3.11"`. **ProphetoVol is pure Python** (DIST-1): the wheel contains Python source and the built front end, nothing is compiled to native code, and no C compiler is needed to build or install it.

| Concern | Choice | Notes |
| --- | --- | --- |
| Storage and queries | **DuckDB**, **Ibis** (`ibis-framework[duckdb]`), **PyArrow** | DuckDB for the catalog, results and reading Parquet; Ibis for every read expression (DATA-81); PyArrow for columnar transfer and Parquet |
| Numerics | **NumPy**, **SciPy** | Vectorized Black-76 and statistics; `scipy.special.ndtr` for the normal CDF |
| Models and validation | **pydantic** v2 | One definition per configurable item (DOC-1) |
| Config files | **PyYAML** | Specs, stress definitions, run configurations |
| Calendar | **exchange_calendars** (`XNYS`) | REF-10. Brings pandas in as a dependency of its own; ProphetoVol's code does not use pandas |
| CLI | **click** | INT-40 |
| Server | **FastAPI**, **uvicorn**, **python-multipart** | M4; listed as core dependencies from the start, as in the profiler, so one install serves the CLI, API and GUI |
| `dev` extra | pytest, pytest-cov, httpx, build, setuptools, wheel | Playwright runs from the front end (§13, decision 1) |

Exact versions are fixed in Phase 0 and recorded in §15. Dependencies are declared once, in `pyproject.toml` (the profiler's convention): `requirements.txt` is `-e .` and `build_requirements.txt` is `-e .[dev]`. Every package installed is recorded there, so the built wheel declares what it needs. Installs go into `.venv` and `frontend/node_modules` only; anything that would install outside the project is confirmed with you first.

### 2.2 Front end (M4)

The profiler's front-end stack, which worked well there:

| Concern | Choice |
| --- | --- |
| Build tool | Vite, building into `src/prophetovol/server/static/` |
| UI | React + TypeScript (strict) |
| Components, forms, charts | Mantine (`@mantine/form`, `@mantine/charts` on Recharts) |
| Routing / server state / tables | React Router, TanStack Query, TanStack Virtual |
| API client | openapi-typescript + openapi-fetch, generated from the server's OpenAPI document (INT-12) |
| Tests | Vitest + React Testing Library; Playwright (TypeScript) for end-to-end tests |

Versions are pinned when M4 starts, in that milestone's own feasibility check. The schema-driven form editor (INT-32) is designed when M4 is detailed (§9).

## 3. Repository Layout

```
.gitignore                     # Phase 1 (§6, Phase 1)
pyproject.toml                 # package metadata; the one list of dependencies
requirements.txt               # -e .
build_requirements.txt         # -e .[dev]
README.md                      # install, demo, import data, publish a spec, run a backtest
docs/
  reference/                   # generated from the schemas (DOC-1, DOC-3); kept current by a test
src/prophetovol/
  __init__.py                  # __version__
  core/                        # errors, CallContext (actor, channel), conventions, time and snapshot types, paging
  registry/
    mechanism.py               # Registry, Implementation metadata (REG-2), discovery (REG-3)
    params/                    # pydantic parameter models of every implementation
  reference/                   # underlyings, data sources, trading calendar, settlement sources (+ default YAML)
  storage/
    adapter.py                 # StorageAdapter interface (DATA-82)
    duckdb/                    # the DuckDB + Parquet adapter: catalog schema, migrations, market files, results
  data/                        # DataManager: ingest, normalization, validation, overlap, versions, coverage
  pricing/                     # Black-76, time to expiry
  engine/                      # step loop, constructor, selectors, conditions, actions, hedging,
                               # sizing, fills, accounting, invariants, MarketDataView
  stress/                      # scenario types, evaluator, modes
  results/                     # snapshot record types, recorder, statistics, export
  runs/                        # BacktestService, RunCoordinator, pre-flight, JobRunner
  server/                      # FastAPI app, security, encoding, routers, static/ (M4)
  cli/                         # click commands
  testdata/                    # synthetic data generator, golden chains, demo content
frontend/                      # M4: Vite + React + TypeScript; e2e/ for Playwright
tests/
  unit/ …                      # per package
  contract/                    # the adapter contract suite (DATA-84)
  golden/                      # hand-checked engine tests (TEST-1)
  acceptance/                  # Appendix B end to end (TEST-11)
  realdata/                    # optional, skipped unless PROPHETOVOL_VENDOR_DATA is set (TEST-10)
```

**Vendor data never enters the repository** (INT-52). Real files stay in a folder outside it, named by the `PROPHETOVOL_VENDOR_DATA` environment variable, with one subfolder per underlying (for example `spx/`), so more underlyings can be added beside SPX. The `.gitignore` also excludes the usual vendor file patterns as a second line of defence.

## 4. Design Across Milestones

### 4.1 The service and its callers (ARC-1)

- **`BacktestService`** is the only entry point. Its collaborators (`DataManager`, `ReferenceData`, `CatalogRepository`, `RunCoordinator`) are internal. The CLI, the API and later an agent call only service methods.
- **`CallContext`** (actor, channel) is passed into every write. The actor is the operating-system user; the channel is `cli`, `api`, `gui` or `library` (AUD-1). The GUI sends a header so the API records `gui` rather than `api`.
- **Readers and the writer** (ARC-4), copied from the profiler's proven pattern: one owning service holds the read-write DuckDB connections; `service.reader()` returns a service on fresh cursors of the same connections for request threads. Long writes run on the job worker; quick writes (publishing a spec) run on a reader's cursor in their own transaction.
- **Opening a home directory another process holds** fails with a message naming the cause and the remedy (INT-41).

### 4.2 Storage

**Home directory** (`~/.prophetovol`, or `--home` / `PROPHETOVOL_HOME`):

```
catalog.duckdb      definitions, reference data, imports, data versions, runs, jobs, attempts
results.duckdb      run output: snapshots, trades, structures, events, statistics
market/             market snapshots as Parquet: underlying=SPX/year=YYYY/month=MM/<import_id>.parquet
uploads/            uploaded files while they are being ingested (deleted afterwards)
logs/               server log
```

**Catalog** (schema version 1, with a `schema_version` table so later changes migrate in place). Main tables:

- reference: `underlyings`, `data_sources` (versioned definitions, seeded from the package's YAML as version 1)
- data: `imports` (hash, file name, size, rows, underlying, as-of range, quality report as JSON, status, actor, channel, times) and `data_versions` (`underlying`, `as_of`, `import_id`, state `staged | active | superseded | deleted | discarded | purged`, contract count, quality flags, state times)
- definitions: `strategy_specs` and `stress_definitions` (`id`, `version`, canonical JSON, content hash, description, actor, channel, created), `run_config_templates`
- runs: `runs` (configuration, its hash, references, provenance, status, flags), `run_data_versions` (which data versions each run read), `run_registry_versions`
- operations: `jobs`, `attempts`

**Results** (`results.duckdb`): `position_snapshots`, `portfolio_snapshots`, `stress_snapshots`, `trades`, `structures`, `events`, `run_statistics`, `run_monthly_pnl`, all keyed by `run_id`. Structure snapshots are a view (RES-11).

**Market snapshots** are Parquet files, one per import per month partition (DATA-80), with the vendor columns and every derived column of Appendix A, sorted by `(as_of, root, expiration, option_type, strike)` in row groups of about 20,000 rows. A row is identified by `(underlying, as_of, root, expiration, strike, option_type)`, which `osi_symbol` encodes (DATA-2). A run reads only active versions: a join of the files' `(as_of, import_id)` against `data_versions` where the state is `active` (DATA-80).

**Ingest writes files under the new `import_id` before anything is active** (DATA-11). Commit, replace, add-new-only, delete and invalidation only change rows in `data_versions` and `runs`, inside one catalog transaction, so they are atomic (DATA-32). Discard deletes the import's files. Purge deletes files whose versions are all superseded or deleted, and rewrites a file without the purged dates when only some of its dates are purgeable (as after add-new-only).

**The `StorageAdapter`** (DATA-82) has the operations the requirements list plus catalog reads and writes. Above it, code deals only in underlyings, as-of times, snapshots and versions (DATA-83). DuckDB-specific work (bulk CSV reading, `COPY … TO` Parquet, transactions) lives only in `storage/duckdb/`. Every read query is an Ibis expression (DATA-81).

**The adapter contract suite** (`tests/contract/`, DATA-84) is a pytest suite parametrized by an adapter factory, covering load, overlap, replace, add-new-only, delete, purge, point-in-time reads and atomic run writes. A future adapter passes the same suite.

### 4.3 Ingest pipeline (DATA-10 to DATA-21)

1. **Receive.** One import takes one or more CSV files, folders of them, or zip archives (DATA-3, DATA-4). Each file is streamed into `uploads/` in chunks, never held in memory, while its SHA-256 is computed (DATA-10, DATA-12). The uncompressed size limit (default 2 GB per import) is checked as data arrives.
2. **Parse.** DuckDB reads all the import's CSVs together with every column as text and an explicit header check (DATA-1), so an unparseable value becomes a counted error with examples rather than a failed read. (Phase 0: 4M rows read in about 6 seconds.)
3. **Validate.** Each check in DATA-20 is one SQL aggregate per check per date, with up to five example rows. Duplicates are checked on the contract key, not the vendor symbol. The results form a `QualityReport` (pydantic) stored on the import. Any error stops the import before anything is written.
4. **Normalize and derive** (DATA-13, DATA-14), in SQL, joining two small tables built in Python: the **root table** from the underlying's configuration (vendor root → normalized root, settlement style) and a **calendar table** of trading days from `XNYS` covering the import's dates and expirations.
   - **Times:** `as_of` = the date at 16:15 America/New_York and `index_as_of` = the date at 16:00, stored as UTC instants; `as_of_local` = the same 16:15 as exchange clock time without time zone.
   - **Symbols:** `vendor_root` is parsed from either symbol format (first three characters of a five-character code; the characters before the date in OSI, trimmed); `root`, `settlement_style` come from the root table; `osi_symbol` is built from `root`, expiration, type and strike.
   - **Expiry** (CONV-3): `settlement_date` = the last trading day on or before the expiration date (calendar table); `expiry_timestamp` and `expiry_local` = the settlement date at 09:30 (AM) or 16:00 (PM); `last_trading_date` = the previous trading day for AM, the settlement date for PM.
   - **Time to expiry:** `time_to_expiry_years` = whole minutes between `as_of_local` and `expiry_local`, over 525,600 (exchange clock, CONV-1); `days_to_expiry`; `trading_days_to_expiry` from the calendar table.
   - **Nulls:** `iv = -1` becomes null; on a contract's settlement date `iv` and the greeks become null.
   - **Forwards** (DATA-14): `vendor_forward` as given; `vendor_methodology` from the data source's `per_series_forward_from`; the **parity fit** per `(as_of, root, expiration)` (pairs with valid quotes and both bids above zero, the six strikes with the smallest `|C − P|` by window ranking, `regr_slope`/`regr_intercept` for `D` and `F`, the validity checks), giving `parity_forward`, `parity_discount`, `parity_strikes`; then `forward` and `forward_source` (vendor from the cut-over date; parity before it; the vendor's single price when the fit is invalid, counted as a quality warning). `forward` is null on the settlement date.
5. **Write** Parquet **one month partition at a time** under the new `import_id`, with versions in state `staged`. Phase 0 showed that a single sorted write of a year runs out of memory at a 1 GB limit while per-partition writes do not. Progress is reported per partition (rows and dates done), and cancellation is checked between partitions (INT-24).
6. **Stop for review.** The import waits for the user's commit choice (DATA-30, DATA-31): the quality report and the overlap are shown first.

### 4.4 Reference data and time

- **Underlyings and data sources** (REF-1, REF-5) are versioned definitions, seeded from YAML shipped in the package. SPX ships with every vendor root found in 2007 – 2024 (Phase 0, §15.6), each mapped to its settlement style and normalized root (`SPX` for AM, `SPXW` for PM). `ivolatility_eod` ships with its snapshot times, the exchange-clock time convention, `per_series_forward_from: 2018-06-25` and `parity_strikes: 6`.
- **The trading calendar** wraps `exchange_calendars` `XNYS` behind a small `TradingCalendar` interface: sessions in a range, next and previous session, trading days between two dates, and the package version for provenance (REF-11).
- **Conventions** (§5.4 of the requirements) live in `core/conventions.py` with their documentation, and the published conventions document is generated from it (DOC-3).
- **Time to expiry** (CONV-1) is `(expiry_local − as_of_local)` in whole minutes, divided by 525,600 (minutes in 365 days), on the **exchange clock**, so a daylight-saving change between them is ignored. Phase 0 confirmed that this is the vendor's convention (§15.7). It is computed once at ingest and stored with each row; the same function in `pricing/time.py` is used by ingest (through SQL with identical arithmetic, checked by a test) and by the synthetic generator.
- **Settlement date, expiry and last trading day** (CONV-3) come from the expiration date, the settlement style and the calendar, and are stored at ingest.
- **Trading days to expiry** (CONV-2) and **trading days held** come from the calendar, never from step counts (ENG-4).

### 4.5 Registries (REG-1 to REG-4)

- A generic `Registry` holds named implementations, each declaring a name, a description, a parameter model and an implementation version (REG-2). The service, CLI and API list and describe them with their JSON Schemas (REG-3).
- **Parameter models are kept apart from implementations.** The pydantic parameter models live in `registry/params/`; the implementations live in `engine/`, `stress/` and `pricing/`. The API, the GUI forms and the generated documentation can then read every schema without importing the engine.
- **Specs refer to implementations by name.** A spec field such as `expiration: {selector: target_days, days: 45}` is a pydantic discriminated union built from the registry's parameter models. Its JSON Schema is therefore generated, never hand-written, and a new implementation appears in the schema, the API and the GUI forms automatically.

### 4.6 Market data access and the point-in-time guard (ARC-3, NFR-1)

The run-time target (a single-structure spec over 10 years in under 60 seconds) leaves about **24 ms per step** for everything: reading data, selecting, marking, stress and recording. One new database query per step may not fit in that, so data access is split in two:

- **`MarketDataProvider`** (service side, not in the engine) loads the run's data ahead in **chunks of three months of steps**. For each chunk the adapter supplies the paths of that chunk's partition files, and the provider reads them with one Ibis expression: the active versions as a small in-memory semi-join, only the columns the engine uses, and only the expirations the spec's selectors can reach plus those of contracts already held (NFR-1, third bullet). The result arrives in Arrow, sorted by as-of time, with the offsets of each step's rows precomputed.
- **`MarketDataView`** (given to the engine) is bound to the current step's as-of time and holds a **zero-copy slice** of that step's rows. Every access method takes or implies an as-of time and **raises `PointInTimeError`** for anything stamped after it. The engine never receives the provider, only a view per step. Loading future data into the provider's memory is not a violation; the engine reading it would be, and the guard and TEST-4 prevent that.
- The engine reads the stored derived columns (time to expiry, trading days to expiry, settlement and last trading dates, forward) and never re-derives them.

Phase 0 measured this on ten real years (§15.3): **1.2 ms per step**, against 52–56 ms for one query per step.

### 4.7 The engine (ARC-2, ENG-1 to ENG-43)

- **A pure function of its inputs**: `run_engine(spec, config, stress_definitions, step_schedule, views, calendar, recorder, progress, cancel) → RunOutcome`. No file, database, network or clock access; no randomness; every iteration that affects output is ordered (ENG-10).
- **The step loop** is ENG-1's nine steps, each a separate function, so each can be unit-tested and the order is visible in one place.
- **The constructor interface** (ENG-2) takes the step's view, the book and the spec, and returns orders with reasons. `RulesConstructor` is the Phase 1 implementation.
- **Book state**: structures, legs, positions and the hedge, each with its own quantity, entry details and ledger. Quantities and money are float64; invariants are checked to 1e-6 dollars (§13, decision 6).
- **The step schedule** is fixed by pre-flight (RUN-11): the trading days in range that have data, the skipped missing days, and so the expirations affected by SPEC-55.
- **Run output** is collected by an in-memory `RunRecorder` as columnar buffers (position, portfolio and stress snapshots, trades, structures, events). The service writes it in one transaction when the run ends, whatever its outcome (RUN-23). A 10-year single-structure run holds well under a million rows, so memory is not a concern; Phase 0 confirms the write time.
- **Invariants** (ENG-33) run at the end of every run; a violation fails the run with a diagnostic naming the step and the security.

### 4.8 Jobs (INT-20 to INT-24)

- Jobs are **persisted in the catalog** (INT-22), unlike the profiler's in-memory jobs. A `JobRunner` worker thread takes queued jobs in submission order, one at a time (INT-23).
- Progress is held in memory and written to the catalog at most twice a second and at completion. Cancellation is a flag checked at safe points: between steps for runs, between partitions for ingest (INT-24).
- On opening, jobs and runs left `queued` or `running` by a previous process are marked `failed` with the reason `interrupted` (RUN-20).
- **The CLI runs a job in its own process, in the foreground**, with a progress line, and records it in the catalog like any other job, so job history is the same whichever channel started it.

### 4.9 Audit (AUD-1 to AUD-4)

- Every service operation that can be refused goes through one decorator that writes an `attempts` row with the operation, the parameters' summary, the actor, the channel and the outcome (`ok`, `rejected` with the reasons, or `error`) (AUD-2). Attempts are never deleted.
- Entities record actor and channel on themselves (imports, commits, deletes, purges, published definitions, runs).
- Software versions (RUN-30) are collected by one function used by runs and by `prophetovol --version`.

### 4.10 Schemas and documentation (DOC-1 to DOC-4)

- Every model that a user configures or reads is pydantic with a description on every field. **A test fails if any field lacks a description.**
- Reference documentation (specs, registries, stress, run configuration, snapshots, statistics formulas, conventions) is **generated as reStructuredText** into `docs/reference/` by `prophetovol docs generate`, and a test fails if the committed output is out of date, as the OpenAPI test does (INT-12). A later Sphinx site includes these files directly.
- Docstrings are **reStructuredText with Sphinx field lists** (`:param:`, `:type:`, `:returns:`, `:rtype:`, `:raises:`) (DOC-4). A test checks that public modules, classes and functions in the package have docstrings. Building the Sphinx site itself is later work.

### 4.11 Errors

One exception hierarchy in `core/errors.py` (`NotFoundError`, `ValidationFailed` with field paths, `ImmutableEntityError`, `PointInTimeError`, `HomeLockedError`, …). The CLI prints them readably; in M4 the API maps them to statuses with the profiler's error envelope (NFR-3).

### 4.12 Distribution (DIST-1)

- `python -m build` produces one pure Python wheel containing the package source, its package data (default YAML, demo content) and the built front end. Nothing is compiled or obfuscated, and there is no license check.
- Package data is read with `importlib.resources`, so the package works the same from a wheel, an editable install or a zip.

### 4.13 Testing

| Level | Tool | What |
| --- | --- | --- |
| Unit | pytest | every module; time conventions; selectors, conditions, fills, accounting, Black-76 |
| Contract | pytest | the adapter contract suite (DATA-84) |
| Golden | pytest | hand-checked small chains (TEST-1), expected values worked out by hand and written into the test |
| Property and invariant | pytest | many seeded synthetic runs checked against ENG-33 (TEST-2); determinism (TEST-3) |
| Acceptance | pytest | Appendix B end to end on synthetic data (TEST-11) |
| Real data | pytest, optional | skipped unless `PROPHETOVOL_VENDOR_DATA` is set (TEST-10) |
| API | pytest + httpx | M4: every endpoint against a real service on temporary directories |
| Front end | Vitest | M4 |
| End to end | Playwright | M4: tasks T1–T9 through a real `prophetovol serve` |

Tests use only synthetic data and temporary home directories, apart from the optional real-data suite.

## 5. Phase 0: Feasibility Check

Throwaway scripts in the session scratchpad, not added to the repository. Findings are recorded in §15. Packages installed for it go into `.venv`; their exact versions are recorded in §15 and pinned in `pyproject.toml` when Phase 1 creates it. Phase 0 changes nothing else in the repository.

**Real data** is read from the folder named by the `PROPHETOVOL_VENDOR_DATA` environment variable, outside the repository; nothing from it is copied into the repository. Phase 0 starts by listing the years present. It uses **2024** (recent, with daily PM expirations) and **2008** (older roots and a stress period). The rest of the history is loaded later through the tool itself, as a user would.

| # | Check | Pass condition |
| --- | --- | --- |
| 1 | **Ingest speed.** One real year through the §4.3 pipeline: text read, validation aggregates, normalization, partitioned Parquet writes. | Under 5 minutes (NFR-1), with memory staying bounded. |
| 2 | **Market data read speed.** Ten years of data, made by re-dating the two real years' Parquet, read per step (a) by one Ibis query per step and (b) by monthly chunked loading (§4.6), restricted to the columns and expiry window a 45-day selector needs. | One of them reads a step in ≤ 8 ms on average, leaving most of the 24 ms per step for the engine. If neither does, I check back with you before continuing. |
| 3 | **Readers during writes.** Reader cursors listing imports, coverage and jobs while a worker thread writes Parquet, updates job progress, commits versions and writes a large run result. | No errors; reads stay interactive; readers see only committed data. |
| 4 | **Calendar.** `XNYS` sessions from 2005 to 2026, including unscheduled closures (October 2012, December 2018), against the dates in the real files. | Every file date is a session, or is explained. |
| 5 | **Time convention** (REF-6, open item 2). Solve the vendor's vega (and check delta) for time to expiry on real contracts, at 16:15 snapshots, for AM and PM roots, including dates either side of the March and November DST changes. | Calendar time over 365 days from absolute instants, short of whole days by 15 minutes (PM) and about 6¾ hours (AM), within a stated tolerance. Black-76 reproduces vendor deltas within a tolerance recorded for TEST-5. |
| 6 | **Root inventory.** The distinct option roots, styles and expiration weekdays in both years. | Every root maps to a settlement style and expiry time. Any root not in REF-1 (older data may include others) is brought to you as a requirements change. |
| 7 | **Installs.** All §2.1 packages install into `.venv` on Python 3.12. | Versions recorded in §15, for pinning in Phase 1. |

**Exit:** findings in §15. If a check fails, the plan is revised with you before Phase 1.

## 6. Milestone 1: Data Foundation (detailed)

Delivers requirements §6, §7, §13.3 and §15: package skeleton, service, storage adapter and contract suite, reference data, ingest, validation and quality reports, overlap and commit, versions, delete and purge, coverage, synthetic data generator, data CLI, persisted jobs, audit. Ends with checkpoint 1.

### Phase 1: Repository foundation

- **`.gitignore`**, covering:
  - Python: `__pycache__/`, `*.py[cod]`, `*.egg-info/`, `build/`, `dist/`, `.pytest_cache/`, `.coverage`, `htmlcov/`
  - environments and editors: `.venv/`, `venv/`, `.idea/`, `.vscode/`, `.env`
  - front end: `frontend/node_modules/`, `frontend/dist/`, `frontend/test-results/`, `frontend/playwright-report/`, and the built SPA in `src/prophetovol/server/static/`
  - local data, a second line of defence for INT-52: `*.duckdb`, `*.duckdb.wal`, `.prophetovol/`, `vendor_data/`, `*.parquet` outside `tests/`
- `pyproject.toml` (name `prophetovol`, version `0.1.0`, `requires-python >=3.11`, dependencies and `dev` extra per §2.1, console script `prophetovol`, package data), `requirements.txt`, `build_requirements.txt`, README skeleton.
- The `src/prophetovol/` package tree (§3), `__version__`, the software-versions collector, the error hierarchy, `CallContext`, home directory resolution (`--home`, `PROPHETOVOL_HOME`, default `~/.prophetovol`), logging.
- Test infrastructure: temporary homes, the field-description test (DOC-1) and the docstring-presence test (DOC-4).
- **Tests:** install and import, `prophetovol --version` with software versions, home resolution order, the two meta-tests, and a built wheel that is pure Python (`py3-none-any`) and installs into a clean environment (DIST-1).

### Phase 2: Conventions, time, calendar and registries

- `core/conventions.py` (CONV-1 to CONV-9), with each convention's documentation.
- `pricing/time.py`: time to expiry in years and in fractional calendar days on the exchange clock (CONV-1); settlement date, expiry and last trading day from the expiration date, settlement style and calendar (CONV-3).
- `reference/`: `Underlying` (with the full historical root table) and `DataSource` models with the shipped YAML (REF-1, REF-5); `TradingCalendar` (REF-10, REF-11); the settlement-source registry with `pm_index_close` (REF-20).
- `registry/mechanism.py`: `Registry`, implementation metadata, discovery with JSON Schemas (REG-2, REG-3).
- **Tests** (TEST-5, first part): time to expiry to the minute for AM (09:30) and PM (16:00) expiries from a 16:15 snapshot; a one-day PM weekly showing 0.99 days; as-of and expiry on opposite sides of the March and November DST changes (clock time, not instants); a Saturday-dated AM monthly settling Friday 09:30 with Thursday as its last trading day, and the same when the Friday is a holiday; trading days to expiry across weekends and holidays; every vendor root mapping to its settlement style and normalized root; registry listing and schemas.

### Phase 3: Storage adapter and catalog

- `storage/adapter.py`: the `StorageAdapter` interface (DATA-82).
- `storage/duckdb/`: connections and reader cursors (ARC-4); the catalog schema and migration mechanism (§4.2); market Parquet layout and active-version reads through Ibis (DATA-80, DATA-81); catalog reads and writes for reference data, imports, data versions, jobs and attempts.
- `BacktestService` opening and closing, readers, the home-locked message (INT-41), seeding reference data on first open.
- **The contract suite** (TEST-7) for everything except run writes, which are added in M2 when the result tables exist.
- **Tests:** schema creation and re-opening, migrations from an empty catalog, readers on other threads, locked-home message, the contract suite on the DuckDB adapter.

### Phase 4: Jobs and audit

- `runs/jobs.py`: persisted jobs and the `JobRunner` (§4.8): submission, FIFO single worker, progress, cooperative cancellation, interrupted-job recovery (RUN-20, INT-21 to INT-24).
- The attempts decorator and the actor and channel recording (§4.9, AUD-1, AUD-2).
- **Tests:** job lifecycle, ordering, cancellation of queued and running jobs, recovery after a simulated crash, progress throttling, attempts on success, rejection and error.

### Phase 5: Synthetic data generator

- `testdata/generator.py` (INT-50): a seeded index path; listed expirations with an AM-settled monthly root (`SPX`, third Fridays and exchange-adjusted dates) and a PM-settled root (`SPXW`, weeklies and dailies); strike grids; implied vols from a simple skew-and-term model; Black-76 prices and greeks at the vendor's time convention; bid-ask spreads from a spread model; expiration-day conventions (IV −1, zero greeks, `mean price` 0 when the bid is 0); a configurable share of crossed quotes, zero asks and flagged rows. Output is the exact 22-column vendor CSV (DATA-1), split into several files like the vendor's downloads. An **older-conventions mode** produces five-character codes (including one code used for two contracts on a date), historical roots, Saturday-dated AM monthlies, and a single underlying price per date with discounted deltas (INT-50), so every ingest rule can be tested without vendor data.
- `testdata/golden.py`: tiny hand-checkable chains (a few strikes, two or three expirations, round numbers), used by M2's golden tests.
- `prophetovol testdata generate` (a developer command beyond INT-40; §13, decision 8).
- **Tests:** determinism for a seed; the file parses as vendor format; greeks reproduce Black-76 at CONV-1 exactly (TEST-5, second part); each quirk appears at its configured rate.

### Phase 6: Ingest, normalization, validation and quality reports

- `data/ingest.py`: the pipeline of §4.3 (DATA-1 to DATA-4, DATA-10 to DATA-13), imports of several files, folders or zips, with progress and cancellation; duplicate-hash detection per file (DATA-12).
- `data/derive.py`: the derived columns (DATA-13) and the parity forwards (DATA-14) as SQL over the root and calendar tables.
- `data/validation.py`: every DATA-20 check with its severity, counts per date and examples; the `QualityReport` model, stored permanently (DATA-21).
- **Tests** (TEST-6):
  - every normalization rule and derived column; IV −1 and zero greeks on the settlement date stored as null; `mean price` 0 kept as `vendor_mid` only; crossed quotes and zero asks warned; both roots sharing an expiration date; the `*` column; MM/DD/YYYY
  - both symbol formats, the same five-character code for two contracts on a date (counted, not rejected), `osi_symbol` for both, every historical root normalized
  - Saturday-dated expirations with their settlement and last trading dates; time to expiry from SQL equal to `pricing/time.py` for every row
  - parity forwards on a synthetic chain with a known forward and discount factor (exact recovery), an invalid fit falling back with a warning, the vendor's forward used from the cut-over date
  - every check triggered by a crafted file; multi-symbol and unknown-root rejection; an import of several files and of a folder; zip with several CSVs; the size limit; cancellation between partitions leaving nothing staged

### Phase 7: Overlap, commit, versions, delete, purge, invalidation and coverage

- Overlap report (DATA-30); commit with replace, add-new-only or cancel, atomically (DATA-31, DATA-32); discard.
- Data versions and their states (DATA-40, DATA-41).
- Delete by underlying and range; purge by import or range, including partial-file rewrites (DATA-50, DATA-51); the affected-runs list before confirming (DATA-52); audit records (DATA-53).
- Invalidation (DATA-60, DATA-61, RUN-40): flags runs through `run_data_versions`. Runs don't exist until M2, so this is tested with run rows inserted by the test; M2 only has to record what each run reads.
- Coverage per trading day with import, contract count and quality flags, and the monthly summary (DATA-70).
- **Tests:** the remaining contract-suite cases (overlap, replace, add-new-only, delete, purge, point-in-time reads); atomicity under an injected failure; purge reclaiming files and rewriting partial ones; coverage against the calendar, including missing and non-trading dates.

### Phase 8: Data CLI, documentation and checkpoint 1

- CLI (INT-40, data part): `prophetovol data import <file-or-folder>... [--commit replace|add-new|ask]`, `data list`, `data coverage [--underlying]`, `data quality <import_id>`, `data delete --underlying --from --to`, `data purge …`, `registry list [<type>]`, `registry show <type> <name>`, `jobs list|show|cancel`, `docs generate`.
- README: install, generating test data, importing, coverage, deleting and purging.
- Optional real-data tests (TEST-10, ingest part): ingest real years from both vendor periods (for example 2008 and 2023) and check counts, quirks, coverage, the derived columns, parity forwards against the vendor's after Jun 2018, and the vendor's deltas reproduced from the stored time to expiry (TEST-5), without storing anything in the repository.
- **Tests:** each command on generated data through click's test runner; the `ask` commit flow; the locked-home message.
- **Checkpoint 1 (demo with you):** import real years from both vendor periods through the CLI (each a single import of its several files), read the quality reports, resolve an overlap, view coverage, delete and purge a range.

### M1 test summary

| Suite | Additions |
| --- | --- |
| Unit | conventions, time to expiry, calendar, registries, errors, home resolution, jobs, attempts |
| Contract | load, overlap, replace, add-new-only, delete, purge, point-in-time reads |
| Data | every normalization rule and validation check, vendor quirks, zip and size limits, invalidation, coverage |
| Generator | determinism, vendor format, exact greeks, quirk rates |
| CLI | every data, registry and jobs command |
| Meta | field descriptions, generated docs current, pure Python wheel |
| Real data (optional) | ingest of a real year |

## 7. Milestone 2: Engine Core (phase level)

Delivers requirements §5, §8, §9, §11, §12.1–12.3 and §17's golden and acceptance tests. Detailed with you before it starts.

- **Phase 9: Spec model, validation and publishing.** `StrategySpec`, legs and every selector, schedule, condition, action, hedge and sizing parameter model (SPEC-1 to SPEC-3, REG-1); the dry-run validator with field paths, including reference cycles, band bounds, explicit time units, SPEC-52 and SPEC-53 (SPEC-80); immutable versions with content hashes (VER-1, VER-2); YAML and JSON import and exact round-trip export (SPEC-81); the Appendix B specs as package content (SPEC-82). Tests: TEST-8.
- **Phase 10: Run configuration, pre-flight and market data access.** `RunConfig` (RUN-1) and templates (RUN-2); pre-flight (RUN-10 to RUN-12) producing the step schedule, including SPEC-55 warnings; `MarketDataProvider` and `MarketDataView` with the point-in-time guard (ARC-3, §4.6). Tests: TEST-4.
- **Phase 11: Selection and entries.** Expiration selectors and filters (SPEC-10 to SPEC-15), strike selectors and quote filters (SPEC-20 to SPEC-28), atomic multi-leg selection in dependency order (SPEC-3, SPEC-4), entry schedules (SPEC-30 to SPEC-35). Golden tests for each selector, including `nth_expiration` across a weekend and a holiday.
- **Phase 12: Book, marking, fills, sizing, hedging and accounting.** Quotes and marks with stale handling (ENG-20 to ENG-25); fill models and costs (ENG-40 to ENG-43); sizing and rounding (SPEC-70 to SPEC-73); the hedge band with a fractional hedge (SPEC-60 to SPEC-64); accounting and invariants (ENG-30 to ENG-33); the `RunRecorder`. Golden tests: first-step cost per fill model, notional sizing both roundings, hedge band for example 3, full hedging for example 1, a stale mark.
- **Phase 13: Triggers, rolls, expiry and settlement.** Conditions including dollars per unit (SPEC-41, SPEC-42, SPEC-46), actions and precedence (SPEC-43 to SPEC-45), PM settlement, AM forced closes with the last-valid-mark fallback, early closes for missing expiration days, `expiry_handling` (SPEC-50 to SPEC-55); the full ENG-1 step loop and the rules constructor (ENG-2, ENG-3). Golden tests for each of these.
- **Phase 14: Run lifecycle, results storage and run CLI.** Run statuses, progress, cancellation and interrupted recovery (RUN-20 to RUN-22); the results tables and the single end-of-run write (RUN-23) with its contract-suite cases; provenance (RUN-30); recording read data versions so invalidation works (RUN-40); events (RES-20); `spec` and `run` CLI commands (INT-40).
- **Phase 15: Acceptance, determinism and checkpoint 2.** Appendix B end to end (TEST-11), invariants over many seeded runs (TEST-2), determinism (TEST-3), the run-time measurement against NFR-1, an optional real-data run (TEST-10). **Checkpoint 2:** run the three examples on real data from the CLI and inspect the snapshots and events.

## 8. Milestone 3: Stress and Analytics (phase level)

Delivers requirements §10, §12.4 and §12.5. Detailed with you before it starts.

- **Phase 16: Stress definitions and revaluation.** `StressDefinition` with versions and limits (STR-1, STR-2); `underlying_slide` and the shipped `default_slide` (STR-10, STR-11); vectorized Black-76 on the series forward, sticky strike, null-IV handling (STR-20 to STR-23); stress snapshots per portfolio and structure (STR-50 to STR-52); `stress` CLI commands.
- **Phase 17: Enforcement modes.** The stress gate at ENG-1 step 7: Monitor with would-have-acted flags, Scale to limit with the exact solution, Halt run (STR-30 to STR-35); the checked book with its required hedge (STR-32); breaches with no trade (STR-34). Golden tests: each mode, the exact scaled size, a halt.
- **Phase 18: Statistics and export.** Every RES-30 statistic with `periods_per_year`, each formula documented in its schema (RES-31); the monthly P&L table; CSV, Parquet and JSON export (RES-40). **Checkpoint 3.**

## 9. Milestone 4: Server and GUI (phase level)

Delivers requirements §13 (server, API, GUI, demo) and TEST-9. Detailed with you before it starts, beginning with its own feasibility check of the front-end toolchain and version pins.

- **Phase 19: Server skeleton.** `prophetovol serve`, local security with token, cookie, Host and Origin checks (INT-1 to INT-3), the error envelope, non-finite encoding (INT-13), static SPA serving, the job endpoints. Adapted from the profiler's server modules.
- **Phase 20: The full API.** Every group in INT-10, paged (INT-11); the OpenAPI document kept current by a test, and TypeScript types generated from it (INT-12).
- **Phase 21: Front-end scaffold, Home, Data and Jobs.** App shell, jobs panel with notifications, Home, imports, the upload wizard, coverage heatmap with drill-down, delete and purge (INT-30, INT-31, INT-36).
- **Phase 22: Strategy and stress editors.** Schema-driven forms from the registries' JSON Schemas, with registry pickers, unit pickers, field-level validation from the dry run, YAML view, version history, import and export (INT-32, INT-33).
- **Phase 23: New run and the run page.** Pre-flight findings, start; summary statistics, charts with table views, snapshot tables, step drill-down, structures, events, export (INT-34, INT-35, INT-37).
- **Phase 24: Demo, end-to-end tests and checkpoint 4.** `prophetovol demo` (INT-51); Playwright tests of T1–T9; accessibility checks (NFR-5); README. **Checkpoint 4.**

## 10. Requirement Traceability

| Requirements | Phases |
| --- | --- |
| ARC-1, ARC-2, ARC-4, ARC-5, ARC-7 | 1, 3 (service, readers); 9–13 (pure engine); 2 (registries) |
| ARC-3 (point in time) | 10 |
| ARC-6, INT-1 to INT-3 (local server, security) | 19 |
| TIME-1 to TIME-3, CONV-1 to CONV-9 | 2; applied throughout 9–18 |
| VER-1 to VER-4 | 7 (data versions); 9 (specs); 14 (runs); 16 (stress) |
| REG-1 to REG-4 | 2 (mechanism); 9, 11–13, 16 (implementations) |
| DATA-1 to DATA-21 (format, ingest, derived columns, parity forwards, validation) | 6; 2 (time and expiry functions); 0 (speed, data findings) |
| DATA-30 to DATA-70 (overlap, versions, delete, purge, invalidation, coverage) | 7 |
| DATA-80 to DATA-84 (storage, Ibis, adapter, contract suite) | 3, 7, 14 |
| REF-1 to REF-21 | 2; 0 (timing, roots) |
| SPEC-1 to SPEC-3, SPEC-80 to SPEC-82 | 9 |
| SPEC-4, SPEC-10 to SPEC-35 | 11 |
| SPEC-40 to SPEC-55 | 13 |
| SPEC-60 to SPEC-73 | 12 |
| ENG-1 to ENG-4 | 13 (loop, constructor); 10 (schedule) |
| ENG-10 (determinism) | 12–15 |
| ENG-20 to ENG-43 | 12 |
| STR-1 to STR-52 | 16, 17 |
| RUN-1, RUN-2, RUN-10 to RUN-12 | 10 |
| RUN-20 to RUN-40 | 14; 4 (interrupted recovery) |
| RES-1 to RES-20 | 12–14 |
| RES-30, RES-31, RES-40 | 18 |
| INT-10 to INT-13 (API) | 20 |
| INT-20 to INT-24 (jobs) | 4; 19 (endpoints) |
| INT-30 to INT-37 (GUI) | 21–23 |
| INT-40, INT-41 (CLI) | 8 (data); 14 (spec, run); 16 (stress); 24 (demo) |
| INT-50 to INT-52 (synthetic data, demo, vendor data) | 5; 24 |
| DOC-1 to DOC-4 | 1 (meta-tests); 8 (generation); every phase (descriptions) |
| AUD-1 to AUD-4 | 4; 6, 7, 9, 14 (recorded) |
| DIST-1 (pure Python wheel) | 1 (wheel test); 24 (wheel with the built front end) |
| TEST-1 to TEST-11 | see §11 |
| NFR-1 | 0 (measured); 15 (run time confirmed) |
| NFR-2 to NFR-5 | 19–24 |

## 11. Test Summary

| Requirement | Where |
| --- | --- |
| TEST-1 golden engine tests | M2 phases 11–13, M3 phase 17, with the chains from Phase 5 |
| TEST-2 invariants on seeded runs | Phase 15 |
| TEST-3 determinism | Phase 15 |
| TEST-4 point in time | Phase 10 |
| TEST-5 time convention | Phases 2 and 5; real-data part in Phase 8 |
| TEST-6 ingest quirks | Phase 6 |
| TEST-7 adapter contract suite | Phases 3, 7, 14 |
| TEST-8 validation and round trip | Phase 9 |
| TEST-9 API, front-end, end to end | Phases 19–24 |
| TEST-10 optional real data | Phases 8 (ingest) and 15 (run) |
| TEST-11 Appendix B acceptance | Phase 15 |

## 12. Performance Targets (NFR-1)

The requirements leave the targets to this plan. Agreed Oct 25, 2026; Phase 0's measurements show whether the design meets them:

| Target | Value | Phase 0 measurement |
| --- | --- | --- |
| Ingest one year of SPX (up to ~650 MB CSV) | under 5 minutes | 13–21 s (before the derived columns of v6, which add a few seconds); confirmed again in Phase 8 |
| Single-structure spec over 10 years, data local | under 60 seconds (≈ 24 ms per step) | data access 1.2 ms per step; whole run measured in Phase 15 |
| Market data read per step | ≤ 8 ms average | 1.2 ms (3-month chunks) |
| GUI first content | within 1 second (NFR-2) | measured in Phase 24 |

## 13. Design Decisions Made in This Plan

Confirmed Oct 25, 2026, with decision 9 changed from Google style to reStructuredText.

1. **Playwright runs from the front end, in TypeScript** (`frontend/e2e`), as in the profiler, instead of being in the Python `dev` extra as requirements §16.1 lists. It keeps the Python suite free of Node and browsers.
2. **Parameter models apart from implementations** (§4.5), so schemas can be read without importing the engine.
3. **Chunked market data loading behind a point-in-time view** (§4.6), subject to Phase 0.
4. **Run output collected in memory and written once** (RUN-23, §4.7).
5. **Timestamps are stored in UTC**, and shown in the exchange's time zone (ET).
6. **float64 throughout**, with invariants checked to 1e-6 dollars.
7. **The CLI runs jobs in the foreground** and records them in the catalog (§4.8).
8. **`prophetovol testdata generate`** is a developer command beyond INT-40, used by tests, the demo and you.
9. **reStructuredText docstrings with Sphinx field lists** (DOC-4), so a Sphinx site can be built later.
10. **Reference documentation is generated as reStructuredText** into `docs/reference/` by `prophetovol docs generate`, with a test that it is current.
11. **One Parquet file per import per month**, with one row group per as-of date; purge rewrites files that are only partly purgeable.
12. **Reference data is seeded** from YAML in the package into the catalog as version 1 on first open.
13. **Copied and adapted from the profiler** (no shared code): the local security module, the JSON encoding of non-finite numbers, the reader-cursor pattern, the job runner's structure, and in M4 the front-end shell (layout, jobs panel, paged table). Everything else is written fresh.
14. **Run ids are random** (UUID4). They are excluded from determinism comparisons, which compare everything else.

Added in v3, from Phase 0:

15. **Market data is read in three-month chunks from the chunk's own partition files**, with zero-copy per-step slices (§4.6, §15.3).
16. **Derived columns and parity forwards are computed in SQL at ingest**, over a root table and a calendar table built in Python (§4.3). A test checks that the SQL time-to-expiry arithmetic equals `pricing/time.py` row by row.
17. **Partitions are written one at a time** at ingest (§4.3, §15.2).

## 14. Risks

| Risk | Mitigation |
| --- | --- |
| R1: per-step data access too slow for the 60-second target. | **Retired by Phase 0:** 1.2 ms per step with the §4.6 design. |
| R2: the vendor's time convention differs from the inference. | **Resolved by Phase 0:** exchange clock time (requirements v6, CONV-1); TEST-5 and the real-data suite keep checking. |
| R3: older files contain option roots or quirks the requirements don't cover. | **Resolved by Phase 0** for 2007 – Aug 2024 (requirements v6). Newer files with a new root fail ingest with "unknown root" rather than guessing. |
| R3a: normalizing roots to `SPX`/`SPXW` merges two vendor roots into one contract key on some date. | Not seen in 2007 – 2024 (the key is unique even without the root); the duplicate-contract check rejects it if it ever happens, and requirements open item 9 records the choice for review. |
| R3b: parity forwards are poor where quotes are sparse (early years, long-dated expirations). | Validity checks with a fallback to the vendor's price, counted in the quality report; `parity_strikes` and `forward_source` are stored so poor fits can be found; checked on real data in Phase 8. |
| R4: floating-point drift breaks invariants on long runs. | Tolerance of 1e-6 dollars; per-step sums from the same records; invariant tests on many seeded runs. |
| R5: hand-checked golden tests are slow to write and easy to get wrong. | Tiny chains with round numbers; each expected value derived in a comment beside the assertion; reviewed with you at checkpoint 2. |
| R6: the spec model's discriminated unions become hard to read in schemas and forms. | Built from the registries so they stay consistent; M4's form design is detailed with you before it starts. |
| R7: a 2 GB import or a large purge rewrite takes long on a laptop. | Streaming and per-partition progress with cancellation; Phase 0 measures ingest. |
| R8: vendor data committed by accident. | Kept outside the repository by default; `.gitignore` patterns as a second defence; tests never write vendor data into the tree. |
| R9: scope of four milestones. | Each milestone usable on its own with a demo; M2–M4 re-planned with you before they start. |

## 15. Phase 0 Findings

Run on Oct 25, 2026 (Windows 11, Intel i7-13700KF with 24 threads, 64 GB RAM, Python 3.12.2, DuckDB 2.0.0, Ibis 12.0.0). The scratch scripts were not added to the repository.

**Outcome: the design stands, with one change to market data access (§15.3).** All three performance checks pass by a wide margin. **The real data does not fit several requirements**, though: older symbols, more option roots, Saturday expirations, the vendor's clock convention, and a vendor methodology change in June 2018. These need a requirements revision, agreed with you before Phase 1 (§15.8).

**Data used.** The vendor folder holds SPX from Jan 3, 2007 to Aug 30, 2024: 70 CSV files in 22 folders (the vendor caps a download at about 150 MB, so a year comes in up to five files, newest date first). In total 35.5M rows, 6.5 GB of CSV, about 1.4 GB as Parquet. Rows per year grow from 0.23M (2007) to 4.3M (2021). During Phase 0 the `PROPHETOVOL_VENDOR_DATA` variable pointed to a folder that did not exist, so Phase 0 read `D:\propheto_vendor_data\spx` directly. The variable now names `D:\propheto_vendor_data`, with one subfolder per underlying.

### 15.1 Installs (check 7)

All §2.1 packages installed into `.venv` on Python 3.12.2, to be pinned in `pyproject.toml` in Phase 1:

| Package | Version | Package | Version |
| --- | --- | --- | --- |
| duckdb | 2.0.0 | fastapi | 0.162.0 |
| ibis-framework | 12.0.0 | starlette | 1.10.0 |
| pyarrow | 26.0.0 | uvicorn | 0.54.0 |
| numpy | 2.5.4 | python-multipart | 0.0.32 |
| scipy | 1.18.1 | pytest | 9.1.1 |
| pydantic | 2.14.1 | pytest-cov | 7.1.0 |
| PyYAML | 6.0.3 | httpx | 0.28.1 |
| click | 8.5.0 | build | 1.6.1 |
| exchange_calendars | 4.13.2 | setuptools | 84.2.1 |
| pandas (via exchange_calendars) | 3.1.0 | wheel | 0.48.0 |

### 15.2 Ingest speed (check 1): passes

The §4.3 pipeline (read as text, every DATA-20 check as one aggregate per date with examples, normalization, Parquet per month partition) on real years:

| Year | CSV | Rows | DuckDB memory limit | Total time | Peak working set |
| --- | --- | --- | --- | --- | --- |
| 2023 | 596 MB, 5 files | 4.04M | 2 GB | 13.3 s | 1.18 GB |
| 2021 (largest) | 635 MB, 5 files | 4.29M | 1 GB | 18.2 s | 1.23 GB |
| 2021 | 635 MB | 4.29M | 512 MB | 20.8 s | 0.81 GB |

About 15–25 times faster than the 5-minute target. Reading all 35.5M rows as text takes 4 seconds. ⚠ **Partitions must be written one at a time**: a single sorted `COPY … PARTITION_BY` of a whole year ran out of memory at a 1 GB limit, and per-partition writes fixed it. This is also what the plan wants, for progress and cancellation.

Quality report for 2023 as an example: 37,189 zero asks, 310 crossed quotes, 625,954 vendor-flagged rows (15%), and no other findings. The `*` flag is set on 15–30% of rows in every year.

### 15.3 Market data read speed (check 2): passes, with a design change

Ten real years (Jul 2014 – Aug 2024, 2,560 steps) in the planned layout, reading the columns a 45-day selector needs within its expiry window (about 6,400 contracts per step), with the active-version filter:

| Approach | Per step |
| --- | --- |
| (a) one Ibis query per step over the partitioned dataset | 52–56 ms: **fails** (the whole budget is 24 ms) |
| (b) one Ibis query per month over the partitioned dataset, filtered per step | 7.9 ms: at the limit |
| (c) **one Ibis query per chunk over the chunk's own partition files**, zero-copy slices per step | **2.2 ms** (1-month chunks), **1.2 ms** (3-month), 1.05 ms (12-month) |

**Design change to §4.6:** the `MarketDataProvider` gets the partition file paths for each chunk from the adapter, reads them with one Ibis expression (active versions as a small in-memory semi-join), and the view hands out `pyarrow` zero-copy slices by precomputed date offsets. **Chunks of three months**: ten years of data access then take about 3 seconds of the 60-second budget. ⚠ DuckDB infers the hive partition columns as an integer `year` and a *string* `month` (because of the zero padding). The adapter reads by path and does not rely on these inferred columns.

### 15.4 Reads during writes (check 3): passes

A worker thread wrote 122 Parquet partitions with throttled job-progress updates, committed an activation of 2,560 data versions (held open 0.5 s), and wrote 1.5M result rows in one transaction (held open 0.5 s). Meanwhile three reader threads on cursors (one through Ibis) listed imports and jobs, counted versions by state and counted results:

- no errors; **no reader ever saw a partial activation or partial results**
- plain cursor reads: median 2.9 ms, p95 5.3 ms, max 22 ms; the Ibis reader: median 6.9 ms, max 413 ms (first call)
- ⚠ with progress throttled to twice a second, the final update (120 of 122) was skipped: progress must always be written at completion (§4.8 already says so).

### 15.5 Calendar (check 4): passes

The files have exactly the 4,446 `XNYS` sessions from Jan 3, 2007 to Aug 30, 2024: none missing, none extra, including the unscheduled closures.

### 15.6 Option symbols and roots (check 6): requirements change needed

- **Symbol formats.** Until Feb 11, 2010, option symbols are **five-character OPRA codes** (for example `QSZLH`: root `QSZ`, then month and strike letters). From Feb 12, 2010 they are OSI (`SPXW  240830C01400000`). DATA-13's root parsing covers only OSI.
- **Old codes are not unique.** In 2007–2010, 641 `(date, option symbol)` pairs (1,944 rows) name *different* contracts: different expirations, strikes, even a call and a put. DATA-20's duplicate check would reject those years. **The key `(date, expiration, strike, call/put)` is unique across all 35.5M rows**, with or without the root.
- **Roots.** Beyond `SPX` and `SPXW` (33.9M rows), 1.5M rows (2007 to Jul 2014) use other roots:

  | Roots | Period | Expirations | Settlement implied by the vendor's greeks |
  | --- | --- | --- | --- |
  | 24 old monthly roots (`SZP SXY SPT SXZ SPQ SXB SPX SXM SPZ SYG SZT SPB SYU SXG SZJ SZV SVP SYZ SPL SPV SZU SZD SYV SXJ`) | 2007 – May 2010 | Saturdays | AM, on the Friday before |
  | 9 old quarterly roots (`SZQ SAQ SLQ QSE SQP QZQ QSZ SKQ SQG`) | 2007 – May 2010 | weekdays | PM (about 16:00) |
  | `JXA JXB JXD JXE` (weeklies) | 2007 – May 2010 | Thursdays and Fridays | AM (about 09:30) |
  | `SPXPM` | May 2010 – Apr 2011 | weekdays | AM (about 09:30), despite the name |
  | `SPXQ` (quarterlies) | Apr 2011 – Jul 2014 | weekdays | PM (about 16:00) |

- **Saturday expirations.** Until Feb 2015, standard monthly expirations are dated on the **Saturday** after the third Friday. The vendor's greeks put their expiry at about **09:30 on the Friday before**. CONV-3 (expiry at 09:30 on the expiration date) and SPEC-15/SPEC-51 (last trading day = the trading day before the expiration date, which would be the settlement Friday itself) are wrong for those contracts.

### 15.7 The vendor's time convention (check 5): requirements change needed

Measured two ways: from the vendor's call deltas (precise, valid from June 2018) and from the vega/gamma ratio (about ±15 minutes, valid for every year).

- **From Jun 25, 2018 the convention is confirmed to the minute:** Black-76 on the vendor's forward, undiscounted, at the convention's time to expiry, reproduces the vendor's call deltas with a **median error of 0.000001** (1.36M contracts). Vendor time to expiry × 365 = calendar days − 0.010, which is the 15 minutes from a 16:15 snapshot to a 16:00 PM expiry; AM expiries sit at 09:30.
- **Daylight saving: the vendor uses wall-clock time.** For expirations whose as-of time and expiry fall on opposite sides of a DST change (5,294 cases), the vendor's time differs by exactly 60 minutes from absolute-instant time and by 0 minutes from wall-clock time. CONV-1 must say time to expiry is the difference of **exchange-local clock times** (DST ignored), not of instants.
- **The vendor changed methodology on Jun 25, 2018.** Up to Jun 22, 2018:
  - `stock price for iv` is **one price per date for every expiration**, not a per-series forward. It equals the index close in most 2007–2010 rows, and mostly differs slightly from it after 2011.
  - **Deltas are discounted**: call delta − put delta at the same strike is about 0.994 at 60–120 days (exactly 1.000 from Jun 2018).
  - The vega/gamma ratio still shows calendar time over 365 days, with the Saturday expiries above at the Friday morning.

  This affects the `forward` selector (SPEC-22), the forward used for stress revaluation (STR-20, ENG-23), and, slightly, hedging and delta selection on discounted deltas (SPEC-27, SPEC-61).

### 15.8 Requirements changes needed before Phase 1

**Resolved in requirements v6** (Oct 25, 2026), as follows:
- **1:** adopted, with a normalized OSI-style symbol for every year.
- **2:** `JX*`, `SPXPM` and the old quarterlies are PM-settled; AM roots normalize to `SPX` and PM roots to `SPXW`, to be tried and revisited if it causes issues.
- **3:** settlement on the trading day before a non-trading expiration date, with the forced close on the trading day before that (normally Thursday).
- **4:** exchange clock time, with all derived values stored in their own columns at ingest.
- **5:** option (a), one parity forward per expiration from the strikes nearest the money, used before Jun 25, 2018, with the vendor's forward from then and vendor deltas as given.
- **6:** adopted.

**Parity check** (run after Phase 0, before writing v6). One forward per (date, expiration) from the strikes nearest the money, compared with the vendor's per-series forwards from Jun 25, 2018 (65,043 expirations):

| Strikes used | Median gap | p95 | p99 | Implausible discount factors before Jun 2018 |
| --- | --- | --- | --- | --- |
| 2 (1 each side) | 1.12 bp | 25.3 bp | 81 bp | 2.3% |
| 4 (2 each side) | 1.10 bp | 24.9 bp | 78 bp | 0.31% |
| **6 (3 each side), both bids > 0** | **1.09 bp** | **24.6 bp** | **78 bp** | **0.06%** |

By tenor (6 strikes): median 0.25 bp under 7 days, 0.31 bp at 7–30 days, 0.77 bp at 30–90 days, 0.98 bp at 90 days to a year, 8.5 bp beyond a year. Gaps above 10 bp cluster in 2020–2021 (about 25% of expirations under a year) and are absent in 2023–2024, which points to a vendor-side difference in those years rather than the method. The median implied rate (expirations over 30 days) is 2.8% after Jun 2018 and 0.9% before, which is plausible for each period.

The original list, for reference:

1. **Root parsing and contract identity** (DATA-13, DATA-20, RES-1): parse both symbol formats; identify a contract by `(underlying, expiration, strike, call/put)`, with root and option symbol stored but not used as the key; check duplicates on that key.
2. **Root configuration** (REF-1): add the historical roots of §15.6 with their settlement styles. To confirm: are the `JX*` weeklies and `SPXPM` AM-settled, as the vendor's greeks treat them, or PM-settled, as `SPXPM`'s name suggests?
3. **Saturday expirations** (CONV-3, SPEC-15, SPEC-51): an AM expiration dated on a non-trading day expires at 09:30 on the preceding trading day, and its last trading day is the trading day before that.
4. **Wall-clock time to expiry** (CONV-1, TEST-5): the difference of exchange-local clock times over 365 days, matching the vendor across DST changes.
5. **Data before Jun 25, 2018** (DATA-13, SPEC-22, STR-20, ENG-23): one underlying price instead of per-series forwards, and discounted deltas. Options:
   - (a) derive each expiration's forward at ingest from put-call parity on that day's quotes, recorded with its source (point-in-time, deterministic)
   - (b) use the vendor's single price as the forward for those dates, flagged
   - (c) support only data from Jun 25, 2018 in Phase 1
6. **Import of several files** (DATA-3, DATA-4, INT-40): a year arrives as up to five CSVs. Allow one import from several files or a folder, not only one file or a zip.

## 16. Implementation Notes

Recorded per phase: what was built, what changed from the plan, and test counts.

**Phase 1 (repository foundation), Oct 25, 2026**

- **Files:** `.gitignore`, `pyproject.toml`, `requirements.txt`, `build_requirements.txt`, `README.md`, the `src/prophetovol/` package tree of §3, and `tests/` (`conftest.py`, `unit/`, `meta/`, `packaging/`).
- **`.gitignore`** covers Python build output, environments and editors (`.venv/`, `.idea/`), the front end's build output and the built SPA, and local data as a second defence for INT-52 (`*.duckdb`, `.prophetovol/`, `vendor_data/`, `data_download*.csv`, `*.parquet` outside `tests/`).
- **`pyproject.toml`:** name `prophetovol`, version single-sourced from `prophetovol.__version__` (0.1.0), `requires-python >=3.11`, console script `prophetovol = prophetovol.cli:main`, pytest markers `slow` and `realdata`. Dependencies use **the Phase 0 versions as lower bounds and the next major version as the upper bound** (for example `duckdb>=2.0,<3`), rather than exact pins, so the wheel installs alongside other packages while staying within tested majors.
- **`core/`:**
  - `errors.py`: the exception hierarchy of §4.11, with `ValidationFailed` carrying located `ValidationIssue`s
  - `context.py`: `Channel` and `CallContext` (actor = operating-system user)
  - `home.py`: `resolve_home` (`--home`, then `PROPHETOVOL_HOME`, then `~/.prophetovol`; nothing created)
  - `versions.py`: `SoftwareVersions` and `software_versions()` (RUN-30's list, plus pydantic)
  - `log.py`: `configure_logging` (named `log.py` so it is never confused with the standard `logging` module)
- **CLI:** the `prophetovol` group with `--home` and `--version` (prints ProphetoVol's and the libraries' versions). Commands arrive in later phases. Click help text ends at `\f`, so reST fields stay out of `--help`.
- **Every planned subpackage exists** with a docstring-only `__init__.py`; no licensing package (requirements v4).
- **Meta-tests** (`tests/meta/test_documentation.py`): every pydantic field has a description (DOC-1); every public module, class, function and method has a docstring, and every parameter is documented with `:param name:` (DOC-4). The second is stricter than "has a docstring": it enforces the reStructuredText field-list style.
- **Changed from the plan:** the wheel test installs the wheel with `--no-deps` into an empty target folder and imports it from there, with dependencies taken from the test environment, instead of building a whole new environment, which would need network access during tests. It still proves the wheel is complete and pure Python (`py3-none-any`, `Root-Is-Purelib: true`, no native files, no tests or specs inside).
- **Tests:** 27, all passing in about 3 seconds (unit 23, meta 2, packaging 2).

**Phase 2 (conventions, time, calendar and registries), Oct 25, 2026**

- **`core/types.py`:** `OptionType`, `SettlementStyle`, `Frequency`.
- **`core/conventions.py`:** `CONVENTIONS`, the nine conventions as published text (the source for DOC-3's generated document, with v6's wording); `DAYS_PER_YEAR`, `MINUTES_PER_YEAR`; the dollar-greek formulas of CONV-7.
- **`pricing/time.py`:**
  - `minutes_to_expiry` and `time_to_expiry_years`: exchange-clock minutes over 525,600 (CONV-1). They accept only naive local date-times, so instants cannot be passed by mistake. Seconds are floored.
  - `days_to_expiry`, `local_datetime`, `to_instant`
  - `expiry_dates`: settlement date, last trading day, `expiry_local` and `expiry_timestamp` (CONV-3)
  - `trading_days_to_expiry` (CONV-2)
  - They take any calendar matching the small `SessionCalendar` protocol.
- **`reference/calendar.py`:** `TradingCalendar` over `exchange_calendars` `XNYS` for a fixed range, **1990-01-02 to 2040-12-31**, held as a sorted array, so lookups are binary searches and never depend on today's date. Dates outside the range raise `ConfigurationError`. `nyse_calendar()` shares one instance per process; `version` is the package version (REF-11).
- **`reference/models.py`:** `RootConfig`, `Underlying` and `DataSource` (all frozen, unknown keys rejected). `Underlying` checks that both settlement styles have an expiry time, and that every normalized root is itself a listed root that normalizes to itself with the same settlement style. `root()` raises `ConfigurationError("unknown option root …")` for an unlisted vendor root.
- **`reference/defaults/`:** `SPX.yaml` with all **40 vendor roots** of Phase 0 (24 AM → `SPX`, 16 PM → `SPXW`), and `ivolatility_eod.yaml`. Loaded with `importlib.resources`; declared as package data and checked in the wheel test, including loading the root table from the installed wheel.
- **`registry/mechanism.py`:** `Registry`, `Implementation`, `ImplementationInfo`, `RegistryInfo`. **REG-2 is enforced at registration**: lower-snake-case unique names, a non-empty description and version, and a description on every parameter field.
- **`registry/catalog.py`:** registries are created there, empty; `all_registries()` and `get_registry()` first import the built-in implementation modules, so listings are complete. Phase 2 creates `settlement_source`; later phases add the other REG-1 kinds as their implementations arrive.
- **`reference/settlement.py`:** `pm_index_close` (intrinsic value against the index close on the settlement date) and `settlement_source_for()`, which raises for AM-settled contracts with REF-21's explanation. Its parameter model is in `registry/params/settlement.py`.
- **Changed from the plan:** `tzdata` added as a dependency. Python's `zoneinfo` has no time zone database of its own on Windows, and `tzdata` was only present through pandas.
- **Tests:** 89, all passing in about 3 seconds (unit 85, meta 2, packaging 2). New:
  - TEST-5, first part: PM weekly 0.99 days, AM next-morning expiry, both 2024 DST changes (clock time, which differs from instants by exactly 60 minutes), aware date-times rejected
  - Saturday-dated AM monthly (settles Friday, closes Thursday), including Good Friday 2008 (settles Thursday, closes Wednesday)
  - trading days across Independence Day and Labor Day
  - the calendar's 4,446 sessions from 2007-01-03 to 2024-08-30, matching the vendor files, and the unscheduled closures of 2012, 2018 and 2025
  - every historical root's mapping, and the underlying validation rules
  - registry rules and settlement values

**Phase 3 (storage adapter and catalog), Oct 25, 2026**

- **`core/`:**
  - `records.py`: `DataImport`, `ImportFile`, `DataVersionRecord`, `DefinitionVersion`, `JobRecord`, `AttemptRecord`, and the status enums (`ImportStatus`, `VersionState`, `JobStatus`, `AttemptOutcome`); every instant is an aware UTC datetime
  - `paging.py`: `Page[T]` and `check_page` (offset ≥ 0, 1 ≤ limit ≤ 500, INT-11)
  - `ids.py`: `new_id`, `utc_now`, `canonical_json`, `content_hash` (VER-2); service-side only, never used by the engine
- **`storage/adapter.py`:** the `StorageAdapter` ABC with the operations Phases 3–7 need: lifecycle and readers; versioned definitions; imports with their files and the duplicate-hash lookup (DATA-12); staged market partitions and versions, snapshot reads for review, and discard; jobs; attempts (append-only: no update or delete operation exists). **Commit, overlap, delete, purge and point-in-time reads are added in Phase 7, run writes in Phase 14**, so the interface only declares what is implemented.
- **`storage/duckdb/schema.py`:** `Migration`, `apply_migrations` (each migration in its own transaction, recorded in `schema_version`; refuses a database newer than the code and badly numbered migrations), catalog migration 1 and results migration 1 (empty until Phase 14).
- **`storage/duckdb/adapter.py`:** `DuckDBAdapter.open` creates the home folders, opens both databases, maps a file held by another process to `HomeLockedError` with the remedy (INT-41), and migrates. `reader()` builds an adapter on new cursors (ARC-4). Every catalog read is an Ibis expression (DATA-81). Market partitions are written with PyArrow (zstd, row groups of 20,000) to a `.partial` file, then renamed into place.
- **`runs/service.py`:** `BacktestService.open` (home resolution, storage, calendar, seeding), `reader()`, `close()`, context manager, `underlying()`, `data_source()` and the two lists.
- **Changed from the plan, with reasons:**
  - **One `definitions` table** (kind, key, version, body, hash, actor, channel, time) instead of a table per kind (§4.2's `underlyings`, `data_sources`, and later `strategy_specs`, `stress_definitions`). Every versioned definition follows VER-1 and VER-2 identically, so one table and one code path serve them all; the kind is a column.
  - **Instants are stored as `TIMESTAMP` holding UTC, not `TIMESTAMPTZ`.** Phase 3 found that DuckDB cursors do not inherit a connection's `TimeZone` setting, and that reading `TIMESTAMPTZ` values into Python needs `pytz`, which is not a dependency. Naive-UTC storage needs neither; the adapter converts to and from aware UTC, and refuses naive datetimes on the way in.
  - **The attempts table's time column is `attempted_at`** (`at` is reserved in DuckDB); `AttemptRecord.attempted_at` matches.
  - **Market files are read with `hive_partitioning=False`.** DuckDB otherwise turns the `underlying=/year=/month=` folders into extra columns, the behaviour Phase 0 warned about (§15.3).
  - **Reference data is seeded only where absent.** The first open publishes the shipped SPX and `ivolatility_eod` definitions as version 1; later opens never overwrite them, so changes made through the service (REF-2) are kept. A future package version with changed defaults will need an explicit upgrade step; recorded for later.
- **Tests:** 121, all passing in about 8 seconds (unit 99, contract 18, meta 2, packaging 2). New:
  - the contract suite's Phase 3 cases (TEST-7), parametrized by adapter: lifecycle and reopening, definition versioning (unchanged content publishes nothing, key order irrelevant), imports (round trip, updates, newest-first paging with totals and filters, paging validation, duplicate-hash lookup ignoring discarded imports), staged partitions and versions (listing, filters, snapshot reads by date and column, a partition written once, discard), jobs, attempts, readers on other threads while the owner writes
  - migrations: order, idempotence, rollback of a failing migration, refusal of newer databases
  - the file layout, naive-UTC storage, and refusing to discard an activated import
  - the service: seeding with the opener's actor and channel, no reseeding or overwriting on reopen, `PROPHETOVOL_HOME`, readers, and **a real second process holding the home directory**, reported as in use and free again once it closes

**Phase 4 (jobs and audit), Oct 25, 2026**

- **`runs/jobs.py`:**
  - `JobRunner`: one daemon worker thread takes job ids from a FIFO queue (INT-23). Submission, cancellation and the worker each use their own cursor (`storage.reader()`), since DuckDB connections are not thread-safe. A lock-guarded in-memory state per job settles the race between a cancel and the worker picking up the same job.
  - `JobContext`, given to handlers: `params`, `context`, `progress()` (written at most every 0.5 s), `check_cancelled()` (raises `JobCancelled` at a safe point), `save()`.
  - `execute_job`, shared by the runner and the CLI's foreground path: records `running`, then `succeeded` with the handler's result, `cancelled`, or `failed` with the message. A handler's exception is recorded, not propagated; `KeyboardInterrupt` is recorded as "cancelled by the user" and then propagated. The final save always carries the last reported progress (the §15.4 finding).
  - `recover_interrupted_jobs`: jobs found queued or running are marked failed with `INTERRUPTED_MESSAGE` (RUN-20); runs join this in Phase 14.
  - `JobRunner.stop()`: lets the running job finish, then marks queued jobs cancelled with `STOPPED_MESSAGE`, so a clean shutdown is not later reported as a crash.
  - Cancelling a finished job raises `ImmutableEntityError`; an unknown kind is refused at submission.
- **`runs/audit.py`:** `@audited(operation)` for service methods that take `context`. It appends one attempt per call: `ok`; `rejected` for any `ProphetoVolError` (validation, refusals, not found), with one reason per validation issue including its field path; or `error` for anything else. The exception is re-raised unchanged, and a failure to write the attempt is logged but never hides the operation's own result. `summarize_params` keeps simple values (strings shortened to 200 characters) and records containers by size.
- **`runs/service.py`:**
  - recovers interrupted jobs on open (`recovered_jobs`)
  - `start_jobs(handlers)` (owner only, once), `stop_jobs()` (also called by `close()`), `jobs`, `submit_job`, `run_job` (foreground), audited `cancel_job`, `get_job`, `page_jobs`, `page_attempts`
  - the first audited write operations: `publish_underlying` and `publish_data_source` (REF-2), which validate, convert pydantic errors to located `ValidationFailed` issues (`ValidationFailed.from_pydantic`), and publish through VER-1's unchanged-content rule
- **Decision:** `submit_job` and `run_job` are plumbing and are not audited themselves. The domain operations that start jobs (import, commit, purge, run) are audited, so each request appears once in the attempts log.
- **Tests:** 143, all passing in about 11 seconds (unit 121, contract 18, meta 2, packaging 2); the threaded tests passed eight repeated runs. New:
  - success with result, progress and times; strict FIFO with no overlap; a failing job followed by one that still runs
  - cancelling a queued job (immediate, never runs) and a running job (stops at a safe point); refusing to cancel a finished job
  - stop: running job finishes, queued jobs cancelled
  - progress throttling with a fake clock, with the final value always written
  - `KeyboardInterrupt`; recovery of queued and running jobs, directly and on reopening a home directory
  - attempts for ok, rejected (with field paths), error, and a failing attempt write; the summary rules; the service's job rules

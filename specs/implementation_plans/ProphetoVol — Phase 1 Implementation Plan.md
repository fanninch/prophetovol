# ProphetoVol — Phase 1 Implementation Plan

Oct 25, 2026 · @Chuck · **Status: Agreed (v2). Phase 0 next.** · Implements: *ProphetoVol — Phase 1 Requirements Specification* (v5, agreed), referred to below as "the requirements". IDs such as DATA-31 or ENG-41 refer to that document.

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

**Vendor data never enters the repository** (INT-52). Real files stay in a folder outside it, named by the `PROPHETOVOL_VENDOR_DATA` environment variable. The `.gitignore` also excludes the usual vendor file patterns as a second line of defence.

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

**Market snapshots** are Parquet files, one per import per month partition (DATA-80), with the normalized columns of Appendix A, sorted by `(as_of, expiration, option_type, strike)` with one row group per as-of date, so a read for one date touches one row group. A run reads only active versions: a join of the files' `(as_of, import_id)` against `data_versions` where the state is `active` (DATA-80).

**Ingest writes files under the new `import_id` before anything is active** (DATA-11). Commit, replace, add-new-only, delete and invalidation only change rows in `data_versions` and `runs`, inside one catalog transaction, so they are atomic (DATA-32). Discard deletes the import's files. Purge deletes files whose versions are all superseded or deleted, and rewrites a file without the purged dates when only some of its dates are purgeable (as after add-new-only).

**The `StorageAdapter`** (DATA-82) has the operations the requirements list plus catalog reads and writes. Above it, code deals only in underlyings, as-of times, snapshots and versions (DATA-83). DuckDB-specific work (bulk CSV reading, `COPY … TO` Parquet, transactions) lives only in `storage/duckdb/`. Every read query is an Ibis expression (DATA-81).

**The adapter contract suite** (`tests/contract/`, DATA-84) is a pytest suite parametrized by an adapter factory, covering load, overlap, replace, add-new-only, delete, purge, point-in-time reads and atomic run writes. A future adapter passes the same suite.

### 4.3 Ingest pipeline (DATA-10 to DATA-21)

1. **Receive.** The file is streamed into `uploads/` in chunks, never held in memory, while its SHA-256 is computed (DATA-10, DATA-12). Zip archives are read member by member (DATA-4). The uncompressed size limit (default 2 GB) is checked as data arrives.
2. **Parse.** DuckDB reads the CSV with every column as text and an explicit header check (DATA-1), so an unparseable value becomes a counted error with examples rather than a failed read.
3. **Validate.** Each check in DATA-20 is one SQL aggregate per check per date, with up to five example rows. The results form a `QualityReport` (pydantic) stored on the import. Any error stops the import before anything is written.
4. **Normalize** (DATA-13), in SQL:
   - `as_of` = the date at 16:15 America/New_York; `index_as_of` = the date at 16:00. Both are stored as UTC timestamps; ET is used only for display.
   - `root` is parsed from the option symbol; `settlement_style` and `expiry_timestamp` come from the underlying's root configuration.
   - `iv = -1` becomes null; on a contract's expiration date `iv` and the greeks become null; the `forward` is kept but marked unusable on that date.
5. **Write** Parquet per month partition under the new `import_id`, with versions in state `staged`. Progress is reported per partition (rows and dates done), and cancellation is checked between partitions (INT-24).
6. **Stop for review.** The import waits for the user's commit choice (DATA-30, DATA-31): the quality report and the overlap are shown first.

### 4.4 Reference data and time

- **Underlyings and data sources** (REF-1, REF-5) are versioned definitions, seeded from YAML shipped in the package. SPX ships with roots `SPX` (AM, 09:30) and `SPXW` (PM, 16:00); Phase 0 checks whether older files contain other roots (§5, check 6).
- **The trading calendar** wraps `exchange_calendars` `XNYS` behind a small `TradingCalendar` interface: sessions in a range, next and previous session, trading days between two dates, and the package version for provenance (REF-11).
- **Conventions** (§5.4 of the requirements) live in `core/conventions.py` with their documentation, and the published conventions document is generated from it (DOC-3).
- **Time to expiry** (CONV-1) is `(expiry_timestamp − as_of)` in whole minutes, divided by 525,600 (minutes in 365 days). Both are absolute instants, so a daylight-saving change between them changes the result by an hour. Phase 0 checks that this matches the vendor across DST changes (§5, check 5); if the vendor uses wall-clock time instead, the requirements are revised with you.
- **Trading days to expiry** (CONV-2) and **trading days held** come from the calendar, never from step counts (ENG-4).

### 4.5 Registries (REG-1 to REG-4)

- A generic `Registry` holds named implementations, each declaring a name, a description, a parameter model and an implementation version (REG-2). The service, CLI and API list and describe them with their JSON Schemas (REG-3).
- **Parameter models are kept apart from implementations.** The pydantic parameter models live in `registry/params/`; the implementations live in `engine/`, `stress/` and `pricing/`. The API, the GUI forms and the generated documentation can then read every schema without importing the engine.
- **Specs refer to implementations by name.** A spec field such as `expiration: {selector: target_days, days: 45}` is a pydantic discriminated union built from the registry's parameter models. Its JSON Schema is therefore generated, never hand-written, and a new implementation appears in the schema, the API and the GUI forms automatically.

### 4.6 Market data access and the point-in-time guard (ARC-3, NFR-1)

The run-time target (a single-structure spec over 10 years in under 60 seconds) leaves about **24 ms per step** for everything: reading data, selecting, marking, stress and recording. One new database query per step may not fit in that, so data access is split in two:

- **`MarketDataProvider`** (service side, not in the engine) loads the run's data ahead in chunks (for example a month of steps at a time) through Ibis into Arrow. It reads only the columns the engine uses and only the expirations the spec's selectors can reach, plus those of contracts already held (NFR-1, third bullet).
- **`MarketDataView`** (given to the engine) is bound to the current step's as-of time. Every access method takes or implies an as-of time and **raises `PointInTimeError`** for anything stamped after it. The engine never receives the provider, only a view per step. Loading future data into the provider's memory is not a violation; the engine reading it would be, and the guard and TEST-4 prevent that.

Phase 0 measures both per-step queries and chunked loading on real data before this is built (§5, check 2).

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
- `pricing/time.py`: time to expiry in years and in fractional calendar days (CONV-1); expiry timestamps from root configuration (CONV-3).
- `reference/`: `Underlying` and `DataSource` models with the shipped YAML (REF-1, REF-5); `TradingCalendar` (REF-10, REF-11); the settlement-source registry with `pm_index_close` (REF-20).
- `registry/mechanism.py`: `Registry`, implementation metadata, discovery with JSON Schemas (REG-2, REG-3).
- **Tests** (TEST-5, first part): time to expiry to the minute for AM (09:30) and PM (16:00) expiries from a 16:15 snapshot, a one-day PM weekly showing 0.99 days, DST changes per the Phase 0 finding; trading days to expiry across weekends and holidays; calendar edge cases; registry listing and schemas.

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

- `testdata/generator.py` (INT-50): a seeded index path; listed expirations with an AM-settled monthly root (`SPX`, third Fridays and exchange-adjusted dates) and a PM-settled root (`SPXW`, weeklies and dailies); strike grids; implied vols from a simple skew-and-term model; Black-76 prices and greeks at the vendor's time convention; bid-ask spreads from a spread model; expiration-day conventions (IV −1, zero greeks, `mean price` 0 when the bid is 0); a configurable share of crossed quotes, zero asks and flagged rows. Output is the exact 22-column vendor CSV (DATA-1).
- `testdata/golden.py`: tiny hand-checkable chains (a few strikes, two or three expirations, round numbers), used by M2's golden tests.
- `prophetovol testdata generate` (a developer command beyond INT-40; §13, decision 8).
- **Tests:** determinism for a seed; the file parses as vendor format; greeks reproduce Black-76 at CONV-1 exactly (TEST-5, second part); each quirk appears at its configured rate.

### Phase 6: Ingest, normalization, validation and quality reports

- `data/ingest.py`: the pipeline of §4.3 (DATA-1 to DATA-4, DATA-10 to DATA-13), with progress and cancellation; duplicate-hash detection (DATA-12).
- `data/validation.py`: every DATA-20 check with its severity, counts per date and examples; the `QualityReport` model, stored permanently (DATA-21).
- **Tests** (TEST-6): every normalization rule; IV −1 and zero greeks on expiration day stored as null; `mean price` 0 kept as `vendor_mid` only; crossed quotes and zero asks warned; both roots sharing an expiration date; the `*` column; MM/DD/YYYY; every check triggered by a crafted file; multi-symbol and unknown-root rejection; zip with several CSVs; the size limit; cancellation between partitions leaving nothing staged.

### Phase 7: Overlap, commit, versions, delete, purge, invalidation and coverage

- Overlap report (DATA-30); commit with replace, add-new-only or cancel, atomically (DATA-31, DATA-32); discard.
- Data versions and their states (DATA-40, DATA-41).
- Delete by underlying and range; purge by import or range, including partial-file rewrites (DATA-50, DATA-51); the affected-runs list before confirming (DATA-52); audit records (DATA-53).
- Invalidation (DATA-60, DATA-61, RUN-40): flags runs through `run_data_versions`. Runs don't exist until M2, so this is tested with run rows inserted by the test; M2 only has to record what each run reads.
- Coverage per trading day with import, contract count and quality flags, and the monthly summary (DATA-70).
- **Tests:** the remaining contract-suite cases (overlap, replace, add-new-only, delete, purge, point-in-time reads); atomicity under an injected failure; purge reclaiming files and rewriting partial ones; coverage against the calendar, including missing and non-trading dates.

### Phase 8: Data CLI, documentation and checkpoint 1

- CLI (INT-40, data part): `prophetovol data import <file> [--commit replace|add-new|ask]`, `data list`, `data coverage [--underlying]`, `data quality <import_id>`, `data delete --underlying --from --to`, `data purge …`, `registry list [<type>]`, `registry show <type> <name>`, `jobs list|show|cancel`, `docs generate`.
- README: install, generating test data, importing, coverage, deleting and purging.
- Optional real-data tests (TEST-10, ingest part): ingest a real year and check counts, quirks and coverage, without storing anything in the repository.
- **Tests:** each command on generated data through click's test runner; the `ask` commit flow; the locked-home message.
- **Checkpoint 1 (demo with you):** import a real year through the CLI, read the quality report, resolve an overlap, view coverage, delete and purge a range.

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
| DATA-1 to DATA-21 (format, ingest, validation) | 6; 0 (speed) |
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

| Target | Value | Measured in |
| --- | --- | --- |
| Ingest one year of SPX (~750 MB CSV) | under 5 minutes on this laptop | Phase 0, Phase 8 |
| Single-structure spec over 10 years, data local | under 60 seconds (≈ 24 ms per step) | Phase 0 (data access), Phase 15 (whole run) |
| Market data read per step | ≤ 8 ms average | Phase 0 |
| GUI first content | within 1 second (NFR-2) | Phase 24 |

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

## 14. Risks

| Risk | Mitigation |
| --- | --- |
| R1: per-step data access too slow for the 60-second target. | Phase 0 measures two approaches on real data; the design (§4.6) already allows chunked loading; a failure comes back to you before building. |
| R2: the vendor's time convention differs from the inference (DST, rounding to the minute). | Phase 0 check 5 on real data either side of DST changes; any difference becomes a requirements change agreed with you. |
| R3: older files contain option roots or quirks the requirements don't cover. | Phase 0 check 6 inventories them across 2008 and 2024; the optional real-data suite keeps checking. |
| R4: floating-point drift breaks invariants on long runs. | Tolerance of 1e-6 dollars; per-step sums from the same records; invariant tests on many seeded runs. |
| R5: hand-checked golden tests are slow to write and easy to get wrong. | Tiny chains with round numbers; each expected value derived in a comment beside the assertion; reviewed with you at checkpoint 2. |
| R6: the spec model's discriminated unions become hard to read in schemas and forms. | Built from the registries so they stay consistent; M4's form design is detailed with you before it starts. |
| R7: a 2 GB import or a large purge rewrite takes long on a laptop. | Streaming and per-partition progress with cancellation; Phase 0 measures ingest. |
| R8: vendor data committed by accident. | Kept outside the repository by default; `.gitignore` patterns as a second defence; tests never write vendor data into the tree. |
| R9: scope of four milestones. | Each milestone usable on its own with a demo; M2–M4 re-planned with you before they start. |

## 15. Phase 0 Findings

To be recorded when Phase 0 runs.

## 16. Implementation Notes

Recorded per phase: what was built, what changed from the plan, and test counts.

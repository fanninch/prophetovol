# ProphetoVol — Phase 1 Implementation Plan

Oct 27, 2026 · @Chuck · **Status: Agreed (v5): M2 detailed in §7, with decisions 27–33 and your answers in §7.5; updated for requirements v7. Plan phases 0–8 done and M1 complete (checkpoint 1 held Oct 26, 2026); Phase 9 next.** · Requirement status: *ProphetoVol — Phase 1 Requirement Status*, one row per requirement. · Implements: *ProphetoVol — Phase 1 Requirements Specification* (v7, agreed), referred to below as "the requirements". IDs such as DATA-31 or ENG-41 refer to that document.

## 1. Approach

- **Correct first.** Every number the tool reports must be reproducible and explainable. Hand-checked golden tests (TEST-1) and the accounting invariants (ENG-33) are written with the code they test, not afterwards.
- **Follow the requirements' milestones.** M1 data foundation → M2 engine core → M3 stress and analytics → M4 server and GUI (requirements §21). Each milestone ends usable on its own, with a demo checkpoint.
- **One milestone in detail at a time.** The design that spans milestones (§4: storage, market data access, the engine and registry interfaces, run output, jobs, audit) is settled now, because M1's storage must serve M2's engine. **M1 is planned in detail** (§6), and **M2 in v5** (§7). M3 and M4 are planned at phase level (§8, §9), and each is detailed and reviewed with you before it starts, using what the previous milestone taught us.
- **Back end first.** M1–M3 are the service, the engine and the CLI, tested in pytest. The HTTP API and the GUI are M4, as thin clients of the same service (ARC-1).
- **Check before building.** Phase 0 (§5) tests the assumptions the design rests on, above all whether market data can be read fast enough to meet the run-time target (NFR-1), using your real vendor files.
- **Working rhythm.** Each phase ends with every suite green, its implementation notes added to §16, and the requirement status tracker (*ProphetoVol — Phase 1 Requirement Status*) updated in the same change. **Changes are left uncommitted**: you do all git operations (branches, commits, pushes). Decisions and deviations are recorded as they happen.
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

Ingest is the **`ivolatility_eod` data-source adapter** (DATA-15): it converts the vendor's files into normalized snapshots in ProphetoVol's internal conventions (§5.4 of the requirements), keeping every original value in a `vendor_*` column. Vendor-specific code lives only here (and in the synthetic generator, which writes the vendor format); the engine, selection, hedging and stress read only internal columns. A second vendor would get its own adapter behind the same normalized schema.

1. **Receive.** One import takes one or more CSV files, folders of them, or zip archives (DATA-3, DATA-4). Each file is streamed into `uploads/` in chunks, never held in memory, while its SHA-256 is computed (DATA-10, DATA-12). The uncompressed size limit (default 2 GB per import) is checked as data arrives.
2. **Parse.** DuckDB reads all the import's CSVs together with every column as text and an explicit header check (DATA-1), so an unparseable value becomes a counted error with examples rather than a failed read. (Phase 0: 4M rows read in about 6 seconds.)
3. **Validate.** Each check in DATA-20 is one SQL aggregate per check per date, with up to five example rows. Duplicates are checked on the contract key, not the vendor symbol. The results form a `QualityReport` (pydantic) stored on the import. Any error stops the import before anything is written.
4. **Normalize and derive** (DATA-13, DATA-14), in SQL, joining two small tables built in Python: the **root table** from the underlying's configuration (vendor root → normalized root, settlement style) and a **calendar table** of trading days from `XNYS` covering the import's dates and expirations.
   - **Times:** `as_of` = the date at 16:15 America/New_York and `index_as_of` = the date at 16:00, stored as UTC instants; `as_of_local` = the same 16:15 as exchange clock time without time zone.
   - **Symbols:** `vendor_root` is parsed from either symbol format (first three characters of a five-character code; the characters before the date in OSI, trimmed); `root`, `settlement_style` come from the root table; `osi_symbol` is built from `root`, expiration, type and strike.
   - **Expiry** (CONV-3): `settlement_date` = the last trading day on or before the expiration date (calendar table); `expiry_timestamp` and `expiry_local` = the settlement date at 09:30 (AM) or 16:00 (PM); `last_trading_date` = the previous trading day for AM, the settlement date for PM.
   - **Time to expiry:** `time_to_expiry_years` = whole minutes between `as_of_local` and `expiry_local`, over 525,600 (exchange clock, CONV-1); `days_to_expiry`; `trading_days_to_expiry` from the calendar table.
   - **IV and greeks** (DATA-13, DATA-15): the vendor's `iv`, `delta`, `gamma`, `vega`, `theta` and `rho` are kept as `vendor_*` (with `-1` stored as null). The internal `iv` equals `vendor_iv` (`ivolatility_eod` measures time as CONV-1 does, so no rescaling). From the data source's `internal_greeks_from` date the internal greeks are copied from the vendor's (`greeks_source = vendor`); before it they are **recomputed with Black-76** (`pricing/black76.py`) from `time_to_expiry_years`, `forward` and `iv` (`greeks_source = recomputed`). The recomputation runs per month partition in Python over Arrow arrays (vectorized NumPy), after the SQL derivation. On a contract's settlement date the internal `iv` and greeks are null.
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
- `data/derive.py`: the derived columns (DATA-13) and the parity forwards (DATA-14) as SQL over the root and calendar tables, and the internal IV and greeks (DATA-15), recomputed with Black-76 before the data source's `internal_greeks_from` date.
- `data/validation.py`: every DATA-20 check with its severity, counts per date and examples; the `QualityReport` model, stored permanently (DATA-21).
- **Tests** (TEST-6):
  - every normalization rule and derived column; IV −1 and zero greeks on the settlement date stored as null; `mean price` 0 kept as `vendor_mid` only; crossed quotes and zero asks warned; both roots sharing an expiration date; the `*` column; MM/DD/YYYY
  - both symbol formats, the same five-character code for two contracts on a date (counted, not rejected), `osi_symbol` for both, every historical root normalized
  - Saturday-dated expirations with their settlement and last trading dates; time to expiry from SQL equal to `pricing/time.py` for every row
  - parity forwards on a synthetic chain with a known forward and discount factor (exact recovery), an invalid fit falling back with a warning, the vendor's forward used from the cut-over date
  - internal greeks: before `internal_greeks_from`, recomputed (equal to Black-76 from the stored time to expiry, forward and IV; call delta − put delta = 1 where call and put share an IV), with the vendor's discounted values kept in `vendor_*`; from it, copied from the vendor; `greeks_source` set accordingly; nothing in the engine-facing columns comes from a vendor-specific convention
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

## 7. Milestone 2: Engine Core (detailed)

Delivers requirements §8, §9, §11 and §12.1–12.3, the spec and run parts of §5, and §17's golden tests (TEST-1 apart from the stress modes, which are M3), invariant, determinism, point-in-time and acceptance tests. Ends with checkpoint 2.

*Detailed and agreed Oct 27, 2026, as plan v5.* It expands the phase-level outline agreed in v4, using what M1 taught us (§7.1). Its decisions are 27–33 in §13, and your answers to the questions asked before Phase 9 are in §7.5.

### 7.1 What M1 changes for M2

- **Data volume per step.** Real 2023 data has about 16,000 contracts per step: 4.04M rows over 250 days, including the dailies. Phase 0's 6,400 per step was for a 45-day window. The engine therefore works on one step's Arrow columns with NumPy masks; it never builds a Python object per contract. Only held contracts and the few chosen at selection become objects.
- **Versioned definitions already exist.** The catalog's `definitions` table versions and hashes underlyings and data sources (VER-1, VER-2). Specs and run-configuration templates reuse it rather than the separate tables §4.2 listed (decision 27).
- **Readable output from the start.** Checkpoint 1 showed what makes CLI output hard to read: instants instead of dates, unaligned tables, detail before summary. The spec and run commands use the helpers that fixed it: aligned tables, trading dates, plurals, summaries first, and `--json` for scripts.
- **Foreground jobs work.** The CLI's foreground jobs, with Ctrl+C as cancellation and the job recorded in the catalog, worked through checkpoint 1. Runs use the same path (decision 7).
- **Generated documentation grows.** `docs generate` adds the spec, run configuration and result models, and the new registries.
- **Real data for checkpoint 2.** The demo home has 2008 and 2023. Checkpoint 2 needs Apr–Jun 2024, the dates of Appendix B's run configuration, and the run-time measurement needs ten years (Phase 15).

### 7.2 Package layout added in M2

```
strategy/          model.py (StrategySpec, Leg, Trigger, …), validate.py (dry run), io.py (YAML/JSON,
                   canonical form, export), examples/ (Appendix B specs as package data)
registry/params/   selection.py, schedules.py, triggers.py, hedge.py, sizing.py, fills.py
engine/            view.py, schedule.py, book.py, orders.py, selection.py, entries.py, triggers.py,
                   expiry.py, marking.py, fills.py, sizing.py, hedging.py, accounting.py,
                   invariants.py, constructor.py, gate.py, loop.py
results/           records.py (position and portfolio snapshots, trades, structures, events),
                   recorder.py (RunRecorder)
runs/              config.py (RunConfig, templates), preflight.py, provider.py (MarketDataProvider),
                   coordinator.py (RunCoordinator)
cli/               spec and run commands
```

`strategy/` is a package beside those in §3 (decision 28). The spec is neither a registry's parameters nor engine code, and the API, the GUI forms and the documentation read it without importing the engine (as decision 2 does for parameter models).

### 7.3 Engine types shared by phases 11–13

- **Contract key:** `(root, expiration, strike, option_type)`, encoded by `osi_symbol` (DATA-2); the underlying is the run's.
- **`MarketDataView`:** one step's rows as Arrow columns, holding only the columns the engine uses, with the step's `as_of` and `index_level`. It offers:
  - lookup by contract key, through an index built on first use
  - the step's expirations with their settlement style, settlement date, last trading date, expiry and days to expiry
  - column arrays for vectorized selection

  Every method takes or implies an as-of time and raises `PointInTimeError` for a later one (ARC-3).
- **`Book`:** structures in opening order. Each `Structure` has:
  - its id, its parent's id (after a structure roll), its units `N`, and the step and date it opened
  - its legs, in spec order. Each leg holds its current position: the contract, signed quantity, entry fill, last valid mark and the step of that mark, and a count of stale steps.
  - its hedge holding `h`
  - its ledger: cumulative P&L and fees
  - its status: `open`, `closing` (a close is waiting for a fill) or `closed`
- **`Order`:** `open` or `close`, with the structure id, the leg id or `hedge`, the contract key, the signed quantity, a reason (entry, the trigger's name, roll, `forced_close_am`, `forced_close_missing_expiry`, `expiry_handling` or hedge) and whether it is forced. **`Fill`:** the order, its price, fees and mark source (`fill`, or `stale` for a forced close at the last valid mark).
- **Constructor** (ENG-2): `propose(view, book, step) → orders with reasons`, covering ENG-1 steps 4–6. The loop owns steps 1–3 and 7–9, so an agent constructor (roadmap) replaces only this.
- **`OrderGate`** (ENG-1 step 7): sizing happens first, then the gate. M2 ships a pass-through gate; M3 replaces it with the stress modes without changing the loop (decision 32).
- **`RunRecorder`:** columnar buffers appended per step, finished into Arrow tables for the single write at the end (RUN-23).
- **Order of everything** (ENG-10):
  - structures in opening order, legs in spec order, triggers in their listed order
  - orders sorted by structure, then leg
  - no iteration over sets or dicts affects output

### Phase 9: Spec model, validation and publishing

- **Registries and parameter models** for every M2 component type (REG-1, REG-2), in `registry/params/`. Each is registered now with its parameter model, description and version, and with its implementation class, whose behavior arrives in phases 11–13 (decision 29). Nothing runs an implementation before Phase 13, and specs validate from Phase 9 on.
  - expiration selectors `target_days`, `trading_days_out`, `nth_expiration`, `same_as_leg`, `next_after_leg`, with the expiration filter model (SPEC-14)
  - strike selectors `delta`, `atm`, `forward`, `same_strike_as`, `strike_offset`, with `on_no_match`
  - entry schedules `once`, `when_flat`, `every_n_trading_days`, `weekdays`
  - the seven trigger conditions, with `unit` where SPEC-41 has it, and the actions `close` and `roll`
  - hedge rules `none` and `band`; sizing `contracts` and `notional`
  - fill models `mid`, `cross_spread`, `mid_plus_fraction`; the constructor `rules`
- **`strategy/model.py`:** `StrategySpec` (SPEC-1), `Leg` (SPEC-2), `Trigger` (SPEC-40), the quote filters (SPEC-28) and `expiry_handling` (SPEC-54).
  - Selector, schedule, condition, hedge and sizing fields are discriminated unions assembled from the registries (§4.5), keyed on `selector`, `schedule`, `condition`, `rule` and `method`, as in Appendix B.
  - Every field is described (DOC-1), with units, defaults and interactions (DOC-2), for example that `cooldown_trading_days` does not delay a roll.
- **`strategy/validate.py`: the dry run** (SPEC-80). It returns a report of errors and warnings, each with a field path such as `legs[1].strike.leg` and a message. Publishing applies the same function. Checks:
  - schema validity, with pydantic's locations turned into field paths
  - unique leg ids; references to existing legs, and not to the leg itself
  - no reference cycles; the cycle is named, and the dependency order is kept for selection (SPEC-3)
  - band bounds `lower ≤ target ≤ upper`
  - roots allowed by the underlying (REF-1); trigger scopes and leg-scoped conditions naming existing legs
  - known registry names, with the known names listed when one is wrong
  - units on time parameters (§7.5, question 3)
  - SPEC-52 as an error with the requirement's exact message, and SPEC-53 as a warning (§7.5, question 4)
- **Publishing** (VER-1, VER-2): `publish_spec` validates, then stores the canonical JSON as a new version (kind `strategy_spec`, key = the spec's `id`). Unchanged content publishes nothing and says so. A spec with errors is refused with its report. Both operations are audited: `spec.validate`, and `spec.publish`, recorded as rejected with the reasons (AUD-2).
- **`strategy/io.py`:** YAML and JSON import (SPEC-81). Export writes the canonical form as YAML, in model field order with every default stated, so re-importing gives the same canonical JSON and the same content hash.
- **`strategy/examples/`:** Appendix B's three specs as package data (SPEC-82), used by the tests now and by `prophetovol demo` in M4.
- **Service:** `validate_spec`, `publish_spec`, `get_spec(id, version)`, `list_specs`, `spec_versions`, `export_spec`.
- **CLI** (INT-40), brought forward from Phase 14 (decision 33): `spec validate <file>`, `spec publish <file>`, `spec list`, `spec show <id>[@version]`, `spec export <id>[@version] [--out FILE]`. They are small, and they let you write and check specs from Phase 9 on.
- **Documentation:** the spec models and the new registries in `docs/reference/`.
- **Tests** (TEST-8):
  - every validation rule, with its field path
  - each registry's names, descriptions and schemas; the three Appendix B specs valid
  - SPEC-52's exact message; SPEC-53's warning, and its absence when a qualifying trigger exists
  - a cycle named; band bounds; an unknown name listing the known ones
  - YAML and JSON imports equal
  - export round trips, identical canonical JSON and hash, for every example and for a spec using every implementation
  - an unchanged republish publishing nothing; versions incrementing; refused publishes in the attempts log
  - each `spec` CLI command

### Phase 10: Run configuration, pre-flight and market data access

- **`runs/config.py`: `RunConfig`** (RUN-1). It has every field of the requirements' table with its default and a description, `fraction` for `mid_plus_fraction`, and STR-40's description of `stress_mode`. Defaults are resolved (`underlying` from the spec), and the resolved configuration has a canonical hash (VER-3).
  - Until M3, attaching stress definitions, or a `stress_mode` other than `monitor`, is refused with a message saying stress arrives in M3 (decision 32).
  - Templates (RUN-2) are named, versioned definitions (kind `run_config_template`), saved and listed through the service. A run always stores the full resolved configuration.
- **`runs/preflight.py`** (RUN-10 to RUN-12): every problem at once, in a `PreflightReport` of errors and warnings, plus the step schedule. It is available on its own as a readiness check and audited (`run.preflight`). It checks:
  - the spec version validates, and the configuration is valid
  - every trading day in the range (REF-10) has an active snapshot, from the data versions without reading Parquet, and no snapshot is empty
  - each snapshot has the columns the selectors need, from the market schema
  - missing days block the run unless `allow_missing_days` is set. Then they are skipped, and the next step's snapshots are flagged `missing_day_before`. A missing day is reported with a warning that PM-settled contracts expiring on it will be closed at the step before (SPEC-55).
- **`engine/schedule.py`: `StepSchedule`.** It is immutable and holds the steps (sequence, date and as-of time at the data source's snapshot time) and the skipped days. It answers what SPEC-55 needs, "does this date have a step" and "the last step before a date", without reading market data.
- **`runs/provider.py`: `MarketDataProvider`** (§4.6, service side).
  - It loads chunks of three months of steps. Each chunk is one Ibis expression over the chunk's own partition files, whose paths come from a new adapter operation.
  - It reads only the versions captured when the run started (decision 30), as a small in-memory semi-join, and only the columns the engine uses.
  - It reads only expirations within the spec's horizon, the most calendar days to expiry any of its selectors can reach (decision 31). Held contracts stay inside the horizon, because their days to expiry only fall.
  - It gives the engine one view per step, never itself.
- **`engine/view.py`: `MarketDataView`** (§7.3) with the point-in-time guard (ARC-3).
- **Contract suite:** market file listing for a date range.
- **Tests:**
  - configuration defaults, descriptions and a hash independent of key order; templates versioned
  - pre-flight on generated data: a complete range passes. A missing day blocks the run, then with `allow_missing_days` is skipped and flags the next step. A missing PM settlement date is warned, an empty snapshot is reported, and several problems are reported together.
  - the provider returns the same rows per step as `read_active_snapshot` for a sample of steps, applies the horizon filter, and handles a run starting mid-chunk and crossing a year end. A commit made after the run starts does not change what it reads.
  - TEST-4: every view method refuses a later as-of time, and the engine is never given the provider
  - a timing check of per-step access on generated data, recorded rather than asserted tightly

### Phase 11: Selection and entries

- **`engine/selection.py`:**
  - **eligibility** (SPEC-15): an expiration is never eligible at or after its expiry, and an AM-settled one never on or after its last trading day
  - **filters** (SPEC-14), including `standard_monthly_only` (§7.5, question 5)
  - **expiration selectors** (SPEC-10 to SPEC-13): `min_days` and `max_days` defaults floored at 0, both tie-breaks, `trading_days_out` with its tolerance, `nth_expiration` counting only expirations that pass the filter, `same_as_leg` and `next_after_leg`
  - **strike selectors** (SPEC-20 to SPEC-24): tolerances and both tie-breaks, and the strike-spacing default, which is the usual spacing around the target (§7.5, answer 6). `on_no_match: nearest_any` records a warning event (SPEC-25).
  - **quote filters** (SPEC-28); null deltas excluded from delta-based selectors (SPEC-26, SPEC-27)
  - **legs resolved in dependency order and atomically** (SPEC-3, SPEC-4). If any leg fails, no structure opens, and a `selection_failed` event names the leg, its selector and the reason, for example "nearest delta 0.07 away, tolerance 0.05".
- **`engine/entries.py`:** the four schedules (SPEC-30 to SPEC-35), with `max_open` and a failed entry retried at the next scheduled step.
  - `when_flat`'s cooldown counts trading days after a `close` action or an expiry; a roll re-establishes at once.
  - `every_n_trading_days` counts trading days on the calendar from the run's first step (ENG-4). A due day that is a skipped missing day has no entry.
  - `weekdays` applies `holiday_shift`.
- **`testdata/golden.py`:** chains for each selector, `nth_expiration` across a weekend and a holiday, a Saturday-dated AM monthly, ties, and null deltas.
- **Tests** (TEST-1, selection part), through views built from golden chains after the ordinary ingest:
  - each expiration selector, including Appendix B's 0DTE (`days: 0.5, max_days: 1`) and dailies (`trading_days_out n: 1` with the PM filter) examples
  - each strike selector and `on_no_match`
  - eligibility at the expiry boundary and on an AM last trading day
  - every quote filter and null deltas
  - an atomic failure and its event; example 2's legs in dependency order
  - each schedule, with cooldown, `max_open` and `holiday_shift`

### Phase 12: Book, marking, fills, sizing, hedging and accounting

- **`engine/marking.py`** (ENG-20 to ENG-25):
  - a valid quote and its mid
  - the last valid mark carried forward, flagged `stale_mark` with an event, and a warning event at each step beyond `stale_mark_warning_steps`
  - settled and force-closed legs' final marks; the hedge marked at the index level
- **`engine/fills.py`** (ENG-40 to ENG-43):
  - the three fill models; commission per contract per side; hedge cost in basis points of traded notional
  - an order on an invalid quote: opening orders dropped (`order_not_filled`), closing orders retried at the next step with the stale mark kept, and forced closes at the last valid mark without fill cost
- **`engine/sizing.py`** (SPEC-70 to SPEC-73): `contracts`, and `notional` at the entry step's index level.
  - `whole` rounding rounds down, and an entry below one unit is skipped with an event; or `fractional`.
  - A structure roll re-sizes; a leg roll keeps its quantity.
- **`engine/hedging.py`** (SPEC-60 to SPEC-64):
  - the band measure per structure after the step's option trades; trade to `target` when it is outside the band
  - the fractional hedge, never rounded
  - null deltas counting as zero after settlement
  - the hedge closed with its structure (§7.5, question 2), trading at the index level (ENG-25)
- **`engine/accounting.py`** (ENG-30 to ENG-32): per security, market value, cash flows, fees, period and cumulative P&L; equity; dollar greeks (CONV-7), and `h · S` for the hedge (RES-2).
- **`engine/invariants.py`** (ENG-33): the three invariants to 1e-6 dollars (decision 6). A violation fails the run with a diagnostic naming the step and the security.
- **`results/records.py` and `results/recorder.py`:**
  - the position snapshot with every RES-1 field
  - the portfolio snapshot (RES-10), with the worst stress loss null until M3
  - trades, structures, and events (RES-20)
  - pydantic models with described fields for the schema and documentation (DOC-1), recorded as columnar buffers
- **Golden tests** (TEST-1, book part), each run checked against the invariants:
  - the first-step cost under each fill model, with commission
  - notional sizing with `whole` and `fractional` rounding, including a size below one unit being skipped
  - example 3's hedge band: no trade inside the band, and the exact hedge back to +0.03 outside it
  - example 1's full hedging at every step
  - a stale mark carried across a missing quote, with the warning after `stale_mark_warning_steps`; a closing order retried
  - dollar greeks worked out by hand

### Phase 13: Triggers, rolls, expiry, settlement and the step loop

- **`engine/triggers.py`:**
  - the conditions (SPEC-41) with their units. A condition needing a null greek is false and records `condition_null_greek` (SPEC-42).
  - P&L per unit (SPEC-46), from the structure's ledger including its hedge and fees. It keeps accumulating across leg rolls and starts again after a structure roll.
  - the actions (SPEC-43) and their precedence, with every fired trigger in the event (SPEC-44); a roll whose opening side fails selection (SPEC-45)
  - a roll whose closing side cannot fill (§7.5, question 1)
- **`engine/expiry.py`:**
  - PM settlement at intrinsic value against the index level at expiry, through `pm_index_close` (SPEC-50)
  - AM forced closes on the last trading day through the fill model, or at the last valid mark with `forced_close_stale` (SPEC-51)
  - early closes of PM legs whose settlement date is skipped (SPEC-55)
  - `expiry_handling` (SPEC-54)
- **`engine/constructor.py` and `engine/loop.py`:**
  - `RulesConstructor` (ENG-2)
  - `engine/gate.py`: the pass-through `OrderGate` at step 7 (decision 32)
  - `run_engine` with ENG-1's nine steps as separate functions in one visible sequence (§4.7)
  - several structures of one spec at once (ENG-3)
  - every time quantity from timestamps and the calendar (ENG-4)
- **Golden tests** (TEST-1, rules part):
  - the long PM call held to expiry and settled (the chain from Phase 5)
  - a short AM call force-closed with and without a valid quote
  - a PM leg closed at the step before its skipped settlement date
  - a profit target and a stop per unit, including after a leg roll
  - a leg roll on a delta trigger
  - a structure roll on calendar days and on trading days
  - precedence when several triggers fire; each `expiry_handling`; a null-greek condition

### Phase 14: Run lifecycle, results storage and the run CLI

- **`runs/coordinator.py`:** a run is a job of kind `run`. The coordinator runs pre-flight, captures the versions, then the provider, the engine, and one results write (RUN-23).
  - **statuses** (RUN-20): runs left `queued` or `running` are marked `failed` with reason `interrupted` on open, through Phase 4's recovery
  - **progress** (RUN-21): steps done of the total, with the current as-of time
  - **cancellation** at the next step boundary keeps the results (RUN-22)
  - **failures:** an engine failure stores the results up to the failure, marked *partial*; a failed write stores nothing and marks the run `failed`
- **Storage:**
  - Catalog migration 3 extends Phase 7's `runs` table: the spec reference and hash, stress references (empty in M2), the configuration and its hash, provenance, status, error, the partial flag, times, actor and channel. It also adds `run_registry_versions`.
  - `run_data_versions` is filled from the captured versions, so Phase 7's invalidation works on real runs (RUN-40).
  - Results migration 2: `position_snapshots`, `portfolio_snapshots`, `trades`, `structures` and `events`, plus the structure-snapshot view (RES-11). Stress snapshots and statistics come in M3.
  - Adapter: `write_run_results` in one transaction, and paged reads of a run's snapshots, structures and events.
  - Contract suite (TEST-7): atomic run writes, and a failed write leaving nothing.
- **Provenance** (RUN-30): the spec reference and hash, the configuration and its hash, the data versions read, the underlying and data-source versions, the registry versions used, the software and calendar versions, actor, channel, times, status and error.
- **CLI** (INT-40):
  - `run preflight --spec <id>@<v> --config <file>`
  - `run start --spec <id>@<v> --config <file>`: a foreground job with a progress line; Ctrl+C cancels it and keeps the results
  - `run list`
  - `run show <run_id>`: status, the provenance summary, final equity and P&L, counts and flags, with `--structures` and `--events` tables
  - `run cancel <run_id>`, for background runs
  - `run export` and `--stress` arrive with M3 (phases 18 and 16)
- **README:** publishing a spec and running a backtest (DOC-4).
- **Check-in with you** (§7.5, answer 8): one Appendix B run on generated data through the run CLI, before Phase 15.
- **Tests:**
  - each status; a cancellation mid-run keeping results to the last finished step
  - an injected engine failure storing partial results; an injected write failure storing nothing
  - interrupted recovery; complete provenance
  - the *data superseded* flag after a version the run read is replaced or deleted
  - the run commands on generated data; readers listing runs while a run writes

### Phase 15: Acceptance, determinism, run time and checkpoint 2

- **Acceptance** (TEST-11): the three Appendix B examples end to end on generated data through the service, each with its own checks:
  - **example 1:** hedged to flat after every step, and rolled on each of its three conditions
  - **example 2:** four legs sharing one expiration, with the shorts at one strike, and structure rolls at 25 days or fewer
  - **example 3:** net delta per unit inside the band after every step's hedge, and the spread re-established at 15 days
- **Invariants on many seeded runs** (TEST-2): generator seeds × the three examples × variations in fill model, rounding and size.
- **Determinism** (TEST-3): the same inputs twice give identical stored results, apart from run ids and times (decision 14).
- **Run time** (NFR-1): a single-structure spec over ten years with the data local, measured on real data in a scratch home outside the repository, against the 60-second target. If it misses, I profile it and decide the remedy with you before checkpoint 2.
- **Optional real-data run** (TEST-10): a sample run on real data in the real-data suite.
- **Checkpoint 2 (demo with you):** import Apr–Jun 2024 (and any other years you like), publish the three examples, and run each from the CLI with Appendix B's configuration. Then inspect the snapshots, structures and events, and review a sample of the golden tests' hand calculations (R5).

### 7.4 M2 test summary

| Suite | Additions |
| --- | --- |
| Unit | spec model, registries, validation, YAML round trip, run configuration, pre-flight, provider, view, each engine module |
| Golden | TEST-1 except the stress modes (M3) |
| Contract | market file listing, atomic run writes |
| Acceptance | Appendix B's three examples (TEST-11) |
| Property | invariants on seeded runs (TEST-2), determinism (TEST-3) |
| CLI | the `spec` and `run` commands |
| Real data (optional) | a sample run; the ten-year run-time measurement in a scratch home |

### 7.5 Answers to the questions before Phase 9

Asked with the v5 draft; answered by you on Oct 27, 2026.

1. **A roll whose closing side cannot fill** (an invalid quote, ENG-41): **the opening side waits.** It is selected and executed at the step where the close fills; until then the structure stays as it is and the close is retried. You noted that in M3 the stress gate also checks any opening order against the risk tolerance, so a new short opened while another cannot be closed would be caught there as well.
2. **A structure close where one leg cannot fill:** handled the same way. The other legs close at once, and the unfilled leg is retried each step (ENG-41). The structure is `closing` until it fills. The hedge keeps being rebalanced on the remaining leg and is closed at the step the last leg closes.
3. **Units on day conditions:** `unit` keeps its `calendar_days` default (SPEC-41), and the dry run warns when it is left out ("calendar_days assumed"). No requirements change.
4. **SPEC-53:**
   - A leg counts as covered by a `leg_days_to_expiry_at_or_below` or `structure_min_days_to_expiry_at_or_below` condition with `days ≥ 1`, in `trading_days` or in `calendar_days`. The intent is to close or roll at least one trading day before expiry, away from the expiration-day data.
   - Over a long weekend a calendar-day trigger can miss. The forced close (SPEC-51) then applies, which you accepted, and the warning text says so.
5. **`standard_monthly_only`:** decided by date, whatever the root. A standard monthly is an expiration whose settlement date is the third Friday of its month, or the trading day before it when that Friday is a holiday; the Saturday-dated monthlies settle on that Friday. Adding `settlement_styles: [AM]` gives the AM-settled monthlies only.
6. **"The series' strike spacing"**, the default `tolerance_points` of `forward` and `strike_offset` when a spec gives none: **the usual spacing around the target**, the most common gap between adjacent listed strikes near the target in that expiration. A hole in the chain, for example from quote filters, gives no match and a `selection_failed` event rather than a strike far from the target. Not a configuration setting: a spec can always state `tolerance_points`.
7. **Golden-test hand checks:** each expected value's derivation is written beside its assertion, and you review a sample at checkpoint 2.
8. **A check-in after Phase 14:** yes. We look at one Appendix B run on generated data through the run CLI before Phase 15.

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

Where each requirement is planned. Whether it is done, and in which phase, is recorded per requirement ID in *ProphetoVol — Phase 1 Requirement Status*.

| Requirements | Phases |
| --- | --- |
| ARC-1, ARC-2, ARC-4, ARC-5, ARC-7 | 1, 3 (service, readers); 9–13 (pure engine); 2 (registries) |
| ARC-3 (point in time) | 10 |
| ARC-6, INT-1 to INT-3 (local server, security) | 19 |
| TIME-1 to TIME-3, CONV-1 to CONV-9 | 2; applied throughout 9–18 |
| VER-1 to VER-4 | 7 (data versions); 9 (specs); 10 (run configurations); 14 (runs); 16 (stress) |
| REG-1 to REG-4 | 2 (mechanism); 9, 11–13, 16 (implementations) |
| DATA-1 to DATA-21 (format, ingest, derived columns, parity forwards, validation) | 6; 2 (time and expiry functions); 0 (speed, data findings) |
| DATA-30 to DATA-70 (overlap, versions, delete, purge, invalidation, coverage) | 7 |
| DATA-80 to DATA-84 (storage, Ibis, adapter, contract suite) | 3, 7, 14 |
| REF-1 to REF-21 | 2; 0 (timing, roots) |
| SPEC-1 to SPEC-3, SPEC-80 to SPEC-82 | 9 |
| SPEC-4, SPEC-10 to SPEC-35 | 11 |
| SPEC-40 to SPEC-55 | 13 |
| SPEC-60 to SPEC-73 | 12 |
| ENG-1 to ENG-4 | 13 (loop, constructor, pass-through order gate); 10 (schedule); 17 (stress gate) |
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
| INT-40, INT-41 (CLI) | 8 (data); 9 (spec); 14 (run); 16 (stress); 24 (demo) |
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

Added in v4, with requirements v7:

18. **Internal conventions with data-source adapters** (DATA-15). Core code (`pricing`, `engine`, `stress`, the conventions module) states ProphetoVol's own conventions and has no vendor-specific parameters; ingest converts into them, and the generator converts out of them to write vendor files. Greeks recomputed at ingest for the pre-June-2018 period are computed with the same `pricing/black76.py` the stress module uses, so there is one Black-76 in the code base.

Added with Phase 6 (details in §16, Phase 6):

19. **The ingest adapter works in its own DuckDB working database** under `<home>/uploads/<import_id>/`, removed afterwards; storage receives finished partitions (DATA-83).
20. **Local CSV files are hashed where they are**, not copied into `uploads/`; zip members are extracted, and HTTP uploads land in `uploads/` (DATA-10).
21. **Validation errors fail the job**; the import is kept as `failed` with its quality report, and nothing is written.
22. **Internal greeks are null whenever the internal IV is null**, so a vendor's zero greeks are never used as real values.

Added with Phase 7 (details in §16, Phase 7):

23. **Unused overlaps from add-new-only are superseded**, retained for review and eligible for purge. They never become active implicitly.
24. **Delete/purge confirmation binds to a hashed preview** of the operation, selection, eligible version identities/states and dependent runs. The worker recomputes it before execution; a changed scope requires a new review.
25. **Purge and discard use a recoverable file journal.** Backups and prepared replacements precede an atomically published manifest. The catalog transaction records the operation id; reopening restores uncommitted originals or cleans committed backups. Reader cursors share a lock for lifecycle writes and file reads.
26. **Invalidation executes inside the lifecycle job's catalog transaction**, as §4.2 specifies, rather than as a separately scheduled job that could leave flags temporarily stale. Phase 7 creates the minimal `runs`, `run_data_versions` and `run_invalidations` tables; Phase 14 extends them through subsequent migrations.

Added in v5, with M2 detailed (§7), agreed Oct 27, 2026:

27. **Specs and run-configuration templates are stored in the existing `definitions` table** (kinds `strategy_spec` and `run_config_template`), which already versions and hashes underlyings and data sources (VER-1, VER-2), instead of the separate tables §4.2 listed.
28. **A `strategy/` package** holds the spec model, its validation, YAML and JSON import and export, and the Appendix B examples, so the API, forms and documentation read the spec without importing the engine.
29. **Every M2 registry is created in Phase 9** with its parameter models, descriptions and versions, so specs validate from Phase 9; each implementation's behavior lands in the phase that builds it.
30. **A run reads the data versions active when it starts.** They are captured once, so a commit, delete or purge during a run cannot change what it reads, and they are what `run_data_versions` records (RUN-40, VER-3).
31. **The provider reads only expirations within the spec's horizon**, the most calendar days to expiry any of its selectors can reach. Selectors without a bound (`nth_expiration`, `next_after_leg`) read every expiration (NFR-1, third bullet).
32. **The stress gate is an `OrderGate` interface** with a pass-through implementation in M2. Attaching stress definitions, and stress modes other than `monitor`, are refused until M3, which replaces the gate without changing the loop.
33. **The `spec` CLI commands move from Phase 14 to Phase 9.**

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
| R10: the Python engine is too slow per step on dense chains (about 16,000 contracts per step in 2023). | One step's Arrow columns with vectorized masks, never a Python object per contract; the provider's horizon filter; a per-step timing check from Phase 10; the whole run measured in Phase 15 and the remedy agreed with you if it misses. |
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

**Phase 5 (synthetic data generator), Oct 25, 2026**

- **`pricing/black76.py`:** vectorized `d1_d2`, `price` (with a discount factor) and `greeks` in the vendor's conventions, confirmed in Phase 0: undiscounted forward delta, optionally scaled by a discount factor (the vendor's pre-Jun-2018 deltas); gamma on the forward; vega per point; theta per calendar day. Stress revaluation in Phase 16 reuses `price`.
- **`data/ivolatility.py`:** the 22 `COLUMNS`, `DATE_FORMAT`, `format_date`, `osi_symbol` and `vendor_root` (both symbol formats). Ingest (Phase 6) reads the format with these; the generator writes it.
- **`testdata/generator.py`:** `GeneratorConfig` (pydantic, every field described), `generate()` and `GenerationSummary`.
  - A seeded GBM index path (rounded to 2 decimals).
  - **Current conventions:** `SPX` AM monthlies on third Fridays (holiday-adjusted), `SPXW` PM weeklies on Fridays and dailies Monday to Thursday.
  - **Older conventions:** Saturday-dated monthlies split across roots by strike range (`SPT`, `SPX`, `SXZ`); `JXA`/`JXB`/`JXD`/`JXE` weeklies; quarterlies under `SZQ` and two Decembers under `SKQ`. The strike code wraps every 26 strikes, so one five-character code names two contracts on a date, as in the real files. One underlying price per date, discounted deltas, integer strikes.
  - **Strike grids are fixed per expiration** when it is first listed, so held contracts appear every day.
  - Skew-and-term vols; Black-76 prices; spreads on 0.05 and 0.10 ticks.
  - On and after the settlement date: IV −1, zero greeks, intrinsic prices; `mean price` 0 whenever the bid is 0.
  - Configurable crossed-quote, zero-ask and flag shares; files split at date boundaries (`data_download.csv`, `data_download2.csv`, …), newest date first.
  - **Greeks are computed from the values as written** (IV 6 decimals, forward 3, index 2), so they reproduce exactly from the file (TEST-5). The same configuration gives byte-identical files.
- **`testdata/golden.py`:** `VendorRow` (every value explicit), `write_rows`, `GoldenChain`, and one example, `pm_call_to_expiry` (three days, strikes 4950/5000/5050, settling at an index of 5050). Phases 11–13 add chains alongside their golden tests.
- **CLI:** `prophetovol testdata generate --out --start --end [--seed] [--conventions current|older] [--rows-per-file]` (decision 8).
- **Found and fixed while building:** on a Good Friday week, the Friday weekly shifts to Thursday and collided with that Thursday's daily under the same root, which would have produced duplicate contracts. Listings are now unique per (expiration, root), and a test checks that contracts are unique per date.
- **Not modeled:** the vendor's 09:30 expiry assumption in its greeks for `JX*` and `SPXPM` (requirements v6, REF-1). The generator uses the true PM expiry, so its greeks follow CONV-3 throughout.
- **Tests:** 172, all passing in about 18 seconds (unit 150, contract 18, meta 2, packaging 2). New:
  - Black-76: closed form, put-call parity, greeks against finite differences, both delta conventions
  - generator: sessions newest first, format and parsing, roots and listing calendars (including Good Friday 2024), unique contracts, fixed strike grids, settlement-date conventions, mean price 0, quirk rates against their configured shares, **greeks reproduced from the file for every live row in both conventions**
  - older conventions: codes, roots, a repeated code with unique contracts, Saturday-dated monthlies settling on the Friday (or the Thursday on Good Friday 2008) with rows ending there, call minus put delta equal to e^(−rT), integer strikes
  - byte-identical output per seed, file splitting at date boundaries, the CLI, and the golden chain's round trip

**Internal conventions change (between Phases 5 and 6, branch `internal_conventions`), Oct 25, 2026**

Not a plan phase: a correction prompted by review, so that ProphetoVol's conventions are its own and vendors are handled by adapters (requirements v7, plan v4).

- **Requirements v7:** §5.4 states that the conventions are ProphetoVol's own; new CONV-10 (prices, IV, greeks: undiscounted forward delta, gamma per forward point, vega per vol point, theta per calendar day); new DATA-15 (data-source adapters: format, timestamps, quirks, forwards, IV rescaling when a source's clock differs, greek recomputation where a source's greeks do not follow CONV-10, original values in `vendor_*`); DATA-13 recomputes greeks before `internal_greeks_from` (replacing v6's "deltas used as given"); REF-5 adds `internal_greeks_from`; CONV-1, CONV-7, SPEC-27, SPEC-42, SPEC-61, SPEC-63, ENG-24, STR-20, RES-1, TEST-5, TEST-6, Appendix A and the glossary reworded.
- **Code:**
  - `pricing/black76.py` documents the internal conventions and **no longer takes `delta_discount`** (a parameter that existed only to imitate the vendor's pre-2018 deltas)
  - `testdata/generator.py` applies the vendor's discount to deltas itself in the older conventions, as the reverse of an adapter
  - `core/conventions.py` gains CONV-10 and rewords CONV-1 and CONV-7; `pricing/time.py`'s docstring cites CONV-1
  - `DataSource` gains `internal_greeks_from` (2018-06-25 for `ivolatility_eod`)
- **Tests:** 177, all passing (unit 155, contract 18, meta 2, packaging 2). New or changed: call delta − put delta = 1 at several strikes and tenors; `greeks` has no vendor-specific parameter; ten conventions, none defined as a vendor's, CONV-10's content; `internal_greeks_from` in the shipped data source; the generator tests apply the vendor's discount outside Black-76.

**Claude Code project configuration (between Phases 5 and 6, branch `claude_project_config`), Oct 25, 2026**

Not a plan phase: the project's rules, which until now lived in a private memory on one machine, move into the repository, versioned and visible to every session.

- **`CLAUDE.md`** (read automatically by Claude Code): where the specifications are, the process (requirements, then plan, then phases; the owner does all git operations; every portion ends with `phase-wrapup`), the architecture rules (`BacktestService` as the only storage owner, `StorageAdapter` and Ibis, the pure point-in-time engine, internal conventions with adapters, registries, jobs and cursors, audit, pure Python, no shared code), code style, commands, the vendor data rules, and the pitfalls found so far.
- **`.claude/settings.json`:** **denies** history-changing git commands (commit, push, pull, merge, rebase, reset, revert, cherry-pick, am, tag, stash, checkout, switch, restore, and branch deletion or renaming) for both shells, so the owner's git rule is enforced rather than remembered; **allows** the routine commands (pytest, the offline editable install, `pip list/show`, `build`, the tracker script, the `prophetovol` console script, read-only git). Prefix rules do not catch every spelling (for example `git -C path commit`); `CLAUDE.md` states the rule as well.
- **`.claude/skills/phase-wrapup/SKILL.md`:** the end-of-portion checklist: suites and test counts, plan §16 notes and status line, the tracker, status lines in the specs README, roadmap and README, a stale-version check, and the report with a commit message.
- **`scripts/update_tracker.py`:** applies row changes and additions from a JSON file, recomputes the summary and per-area counts from the rows, fills plan-phase dates and the M1 status, and checks that the tracker has exactly the requirement IDs of the specification (`--check`). It replaces the throwaway script used for the tracker so far.
- **`.gitignore`:** `.claude/settings.local.json` (personal settings).
- **Tests:** 185, all passing (unit 163, contract 18, meta 2, packaging 2). New: `tests/unit/test_update_tracker.py`: row changes and recounts, added rows, refused mistakes, the coverage check, the command line, and a check that **the real tracker covers the real specification and its stored counts match its rows**, so a mismatch fails the suite.

**Phase 6 (ingest, normalization, validation and quality reports), Oct 26, 2026**

- **`data/schema.py`:** `MARKET_SCHEMA` (Appendix A's 49 columns, internal and `vendor_*`), `ForwardSource`, `GreeksSource`, `VendorMethodology`.
- **`data/quality.py`:** `QualityReport`, `QualityCheck`, `DateCount`, `Severity`; `errors`, `warnings`, `flags_by_date()` (the data versions' quality flags).
- **`data/receive.py`:** `plan_inputs` (files, folders searched recursively, zips; existence, type and size limit checked before anything is read) and `receive` (every file hashed in 8 MB chunks; zip members extracted into the import's working folder as they are hashed).
- **`data/validation.py`:**
  - the header check
  - **structural checks** on parsed rows (errors: unparseable value, several underlyings, unknown underlying, unknown root, not European, duplicate contract; information: repeated vendor symbol, file already imported)
  - **content checks** on normalized rows (warnings: crossed quote, zero ask, IV −1 before settlement, missing vendor forward, no parity forward, missing trading day, not a trading day, low contract count; information: vendor flag)
  - each check is counted per date, with up to five examples
- **`data/derive.py`:** the working database; `load_files` (all CSVs read as text, then parsed); `load_reference` (root table and calendar table); `derive`; `_fit_parity`; `read_partition`; `_recompute_greeks`.
  - `derive` covers normalized roots and `osi_symbol`; settlement date and last trading day by ASOF joins on the calendar; clock-time time to expiry; trading days; internal IV; the parity fit; the forward choice.
  - `_recompute_greeks` runs Black-76 from `pricing/black76.py` over Arrow arrays.
- **`data/ingest.py`:** the job: receive → headers → parse and structural checks → derive and content checks → one partition per month → staged versions. Progress and cancellation at every step; cancellation discards what was written; the working folder is always removed.
- **Service:** audited `import_files(paths, context, data_source, background)` (inputs checked before any job starts), `job_handlers()` (`ingest`), `get_import`, `page_imports`, `quality_report`.
- **Storage change:** `update_import` now also updates the import's `underlying`, which ingest learns only after parsing (found by a test); the contract suite covers it.
- **Decisions made in this phase (also listed in §13):**
  - 19. **The ingest adapter works in its own DuckDB working database** under `<home>/uploads/<import_id>/` (memory-limited, spilling to disk, removed afterwards). Vendor-specific SQL stays in the adapter; storage receives finished partitions through `write_market_partition` (DATA-83). DATA-81's "reads through Ibis" applies to stored data, not to the transformation of incoming files.
  - 20. **Local CSV files are hashed where they are, not copied into `uploads/`.** Copying a year (about 650 MB) would double the I/O for no gain; zip members are extracted, and HTTP uploads (Phase 20) land in `uploads/` as DATA-10 says.
  - 21. **Validation errors fail the job.** The import is kept as `failed`, with its quality report and the error checks named in its error, and nothing is written. The `data.import` attempt records the accepted request; the rejection is on the job and the import.
  - 22. **Internal greeks are null whenever the internal IV is null** (on the settlement date, or where the vendor's IV is −1 or not positive), so a vendor's zero greeks are never used as real values.
- **Found while building:**
  - DuckDB 2.0 renamed `fetch_arrow_table` to `to_arrow_table`, used here through `con.sql(…)`.
  - **On real 2008 data, call delta − put delta departs from 1** where the vendor quotes the call and the put at different IVs (median 0.99996; up to 0.25 off in the wings). The deltas are right. CONV-10's sentence "= 1 at every strike" was imprecise and is corrected in requirements v7 (editorial: "for a call and a put at the same implied vol").
- **Real-data sanity check** (scratch only, not a committed test; the optional real-data tests are Phase 8):
  - **2008:** 321k rows ingested in 4.1 s; all 37 historical roots mapped; parity forwards for 98% of rows, with 104 expirations falling back to the vendor's single price; greeks recomputed.
  - **2023:** 4.04M rows in 27.5 s; vendor forwards and greeks; parity forwards within a median 0.1 bp of the vendor's.
  - ⚠ The `PROPHETOVOL_VENDOR_DATA` variable names `D:\prophetovol_vendor_data`, which does not exist (the files are in `D:\propheto_vendor_data`); fix before Phase 8's real-data tests.
- **Tests:** 211, all passing in about 30 seconds (unit 189, contract 18, meta 2, packaging 2). New, in `tests/unit/test_ingest.py`, 26 tests:
  - **current conventions:** files, rows, versions, partitions and schema; `osi_symbol`; settlement date, last trading day, expiry, **time to expiry equal to `pricing/time.py` for every row**, trading days; Good Friday; settlement-date nulls; vendor forwards and greeks copied; parity as a check; quality warnings and version flags; `vendor_mid`
  - **older conventions:** root normalization and repeated codes; Saturday-dated monthlies, including Good Friday 2008; parity forwards recovering the generator's true forward and discount; greeks recomputed exactly as Black-76 from the stored values, with the vendor's discounted deltas kept
  - **exact parity recovery** on a hand-built chain, to 1e-9, and the fallback to the vendor's single price with its warning
  - **every error check**, each failing the import with nothing written; the misnamed header with missing and unexpected columns; **the warnings**, with the flagged dates
  - folders, files and zips giving the same rows; duplicate files reported; refused inputs audited with no import created
  - cancellation between partitions discarding everything; a background import


**Phase 7 (overlap, commit, versions, delete, purge, invalidation and coverage), Oct 25, 2026**

- **`data/lifecycle.py`:** documented models for commit choices, import/range selections, overlap pairs, affected runs, confirmation previews and daily/monthly coverage.
- **`storage/adapter.py`, `storage/duckdb/lifecycle.py`, `storage/duckdb/adapter.py`:** overlap; atomic replace/add-new/cancel; version transitions; exact active-snapshot reads through Ibis with an optional as-of cutoff; confirmed delete and purge; partial-file rewrites; persisted invalidation dates. Lifecycle writes and file reads share a lock across cursors, preserving one active version under concurrent requests.
- **Recoverable purge/discard:** prepare backups/replacements and publish a manifest before file mutations. Commit an operation marker with catalog state changes. On failure/cancellation restore the originals; after interruption, recover on home open according to the catalog marker. Preparation and replacement boundaries check cancellation. Progress writes stay outside the replacement transaction so cancellation can update the job row without a write conflict.
- **`storage/duckdb/schema.py`:** migration 2 adds minimal run/provenance/invalidations tables and committed file-operation markers. Existing migration 1 is unchanged; real run creation and result tables remain Phase 14. Fixed schema-version reads to fully consume their results before Ibis reuses the connection, exposed by the migration-preservation test.
- **`runs/service.py`:** audited overlap/preview/coverage operations and commit/delete/purge jobs, in foreground or background. Explicit confirmation is required even with no affected runs, and the preview is rechecked when a queued job executes. Execution is audited separately with its job id, so later failures are not hidden by successful submission. Coverage includes missing trading days, non-trading dates with data, imports, counts and quality flags.
- **Plan refinements:** decisions 23–26 above; no requirement changes. Invalidation is atomic with the change inside the submitted lifecycle job. Add-new-only overlaps use the existing superseded state. File journaling strengthens the planned purge against interruption. Phase 10 still supplies the engine-facing `MarketDataView`; Phase 7's cutoff check is at the storage boundary only.
- **Tests:** 241 total (unit 209, contract 28, meta 2, packaging 2). The 30 new cases cover overlap, replace, add-new-only, discard, delete, partial/full purge, active/point-in-time reads, confirmation and stale scopes (including queued execution), exact run invalidation, migration preservation, coverage, concurrent commits, injected rollback failures, cancellation after file replacement, and recovery before/after commit and during preparation.
- **Test mistakes corrected during development:** the unit and contract files initially shared a basename, which conflicts with this repository's pytest import mode; the contract file is now `test_lifecycle_contract.py`.
- **Documentation:** README library examples, current phase status and requirement tracker updated. The two previously reviewed ingest edge cases (apostrophes in paths and duplicate basenames) are not changed in this phase; they remain separate between-phase corrections under the repository process.
- **Next:** Phase 8, data CLI, generated documentation, optional real-data tests and checkpoint 1. M1 remains in progress.


**Phase 8 (data CLI, documentation and checkpoint 1), Oct 26, 2026**

- **`cli/commands.py`:** the `data`, `registry`, `jobs` and `docs` command groups, each a thin call to a `BacktestService` operation.
  - `data import <paths>... [--commit replace|add-new|ask]`: one import of all the files, folders and zips given; it shows the quality report and the overlap, then commits. `ask` prompts with cancel as the default, and end of input or Ctrl+C discards the staged import. A failed validation exits non-zero and names the import, whose report is kept.
  - `data list`, `data quality <import_id> [--details]`, `data coverage [--underlying --from --to --daily]`.
  - `data delete --underlying --from --to` and `data purge --import-id | --underlying --from --to`: an exact preview, including affected runs, then a confirmation (`--yes` for scripts).
  - `registry list [<type>]`, `registry show <type> <name>` (the full parameter schema); `jobs list|show|cancel`; `docs generate [--out] [--check]`.
- **`cli/__init__.py`:** the CLI logs to `<home>/logs/server.log`. Expected errors (`ProphetoVolError`, pydantic validation errors) become short click messages; unexpected ones are logged with their traceback and the user sees only where the details are (INT-41). An unwritable log is itself a readable error.
- **`documentation.py`:** `reference_documents()` renders `docs/reference/` (index, conventions, models, registries) as reStructuredText from the pydantic schemas, registries and conventions. The service's audited `generate_docs` writes them, or with `check` reports which files are stale; the meta-test `test_generated_reference_is_current` fails when the committed files differ (DOC-1, DOC-3).
- **Service:** audited `list_registries`, `list_implementations` (`registry.list`) and `describe_implementation` (`registry.show`); `data_versions` and `import_snapshot` (an import's rows for one date, for review and the real-data tests); `generate_docs`; `cancel_job` refuses clearly when no job runner is running.
- **Small changes made for the CLI:**
  - A failed job's result carries `error_kind` (`expected` or `unexpected`), so the CLI can tell a validation failure from a defect without parsing messages.
  - Ingest records the import id on the job's result before any work, so a failed or cancelled job still links to its import and quality report.
  - Ingest treats `KeyboardInterrupt` like a cancellation, discarding what it wrote.
  - Zip members are imported in file-name order, so an archive gives the same import as its extracted folder.
- **Plan refinements:** no new design decisions and no requirement changes.
- **README:** CLI-first sections for importing, reviewing, committing, coverage, delete and purge, the registry, jobs and docs commands, the real-data tests, and the current status.
- **Real-data tests** (`tests/realdata/test_vendor_ingest.py`, marked `realdata`, skipped unless `PROPHETOVOL_VENDOR_DATA` is set; vendor files are read in place and the home is in pytest's temporary area outside the repository):
  - **2008** (older conventions): 321,408 rows over 253 dates from 1 file, imported through the CLI in one import. Per-date contract counts match the files; coverage and missing trading days agree with the calendar; greeks recomputed and equal to Black-76 from the stored values; five-character vendor symbols, Saturday-dated expirations settling on the Friday, and parity forwards present.
  - **2023** (current conventions): 4,039,670 rows over 250 dates from 5 files. Vendor greeks kept; the vendor's call deltas reproduced from the stored time to expiry with a median error of 3.0e-7 (TEST-5); parity forwards within a median 0.06 bp of the vendor's.
  - **Checkpoint 1 flow** for both years: re-importing one file shows a full overlap, `add-new` activates nothing, the superseded versions are purged, then one day is deleted and purged after confirmation.
  - The `PROPHETOVOL_VENDOR_DATA` problem noted in Phase 6 is fixed; the variable now names the folder that holds the files. All 6 pass in about 60 seconds.
- **Tests:** 275, of which 269 run by default and pass in about 50 seconds (unit 236, contract 28, meta 3, packaging 2); the 6 real-data tests are skipped without the variable. New in `tests/unit/test_data_cli.py`:
  - every data command on generated data through click's test runner
  - the `ask` choices; end of input discarding
  - multiple files and a zip each being one import
  - delete declined, then confirmed, then purge; affected runs named in the preview
  - a failed validation keeping its report link and exiting non-zero
  - readable expected errors; the locked-home message naming the remedy
  - registry schemas; docs generation and the stale check
  - unexpected exceptions and job failures logged but not shown
  - REST-only fields hidden from help; an unwritable log
  - Ctrl+C during ingest discarding the partial import
- **Still open (between-phase corrections, unchanged here):** the two reviewed ingest edge cases from Phase 7. Paths containing an apostrophe are still interpolated into DuckDB SQL in `data/derive.py`. Duplicate base names are now harmless for zip members, which get numbered names, but have not been re-reviewed for folders.
- **Next:** checkpoint 1 demo with you, which completes M1; then Phase 9 (spec model, validation and publishing), the start of M2.


**Checkpoint 1 and CLI corrections (between Phases 8 and 9, branch `checkpoint1`), Oct 26, 2026**

Not a plan phase: the checkpoint 1 demo that completes M1, and corrections to the CLI's output from what it showed.

- **Checkpoint 1, held with the owner on real data** in a separate home outside the repository, through the CLI in a terminal:
  - **Imported 2008** (older conventions, 321,408 rows, 253 dates, one file) and **2023** (current conventions, 4,039,670 rows, 250 dates, five files as one import). Read both quality reports: no errors. Warnings in 2008: zero asks, IV −1 before settlement, and 104 expirations without a parity forward. Warnings in 2023: crossed quotes and zero asks. Both committed with `replace`.
  - **Resolved an overlap:** re-importing the one-day file of 2023 was reported as an already-imported file and a full overlap. It was committed with `replace`, and the superseded copy was purged.
  - **Viewed coverage**, monthly and daily (October 2008: `no_parity_forward` on most days of the crash).
  - **Deleted and purged** Dec 22–31, 2008 (7 days) after each preview. All 9 jobs succeeded.
- **Findings from the demo and what changed** (`cli/commands.py`, `cli/__init__.py`):
  1. The overlap table listed every incoming date even with no overlap. It is now one line when nothing overlaps, and otherwise a table of only the clashing dates.
  2. Snapshots were shown as UTC instants (`2008-01-02T21:15:00+00:00`). Overlap and previews now show the trading date.
  3. Tables were tab-separated and drifted. Columns are now aligned; empty cells show `-`.
  5. `data quality --details` printed the report as raw JSON (2,699 lines for 2023). It now lists each check's dates and counts and its examples, wrapped without splitting an entry; `--json` prints the complete report for scripts.
  6. Counts now take the right number of their noun ("1 date", "1 version", "Activated 1 snapshot"), with thousands separators.
  7. Previews printed an empty affected-runs table. They now say "No runs affected", or list the runs with a note that their results are kept and flagged.
  8. Coverage listed every empty month (168 rows from 2009 to 2022). Each run of months without data is now one row (`2009-01 to 2022-12`), and the heading gives covered and total trading days.
  10. `data list` gave only each import's rows and dates as imported. A new *Active days* column shows how many of its snapshots are active now (for example `246 of 253` after the delete).
  11. `jobs list` had no times or targets. It now shows when each job started (local time) and what it acted on: the import and commit choice, or the underlying and date range.
  - **Found while checking the fixes:** piping output into a command that stops reading (`… | head`) was reported as an unexpected error with a logged traceback. On Windows a closed pipe raises `OSError` `EINVAL` rather than `BrokenPipeError`. The CLI now confirms that standard output is closed and exits with status 1 quietly; other `OSError`s are still unexpected errors.
- **Finding 4, a gap in DATA-20, closed:** on 2008-09-19 the contract count drops about 15% below its neighbours, and nothing flagged it. DATA-20 makes the low-count ratio *configurable* (default 50% of the median of the 5 surrounding dates), but `data/validation.py` had it as a constant.
  - It is now `DataSource.low_contract_ratio` (default 0.5, between 0 exclusive and 1), changed by publishing a new data source version (`publish_data_source`).
  - Ingest passes it to `content_checks`, and the stored check description names the ratio used, so each import's report records its threshold.
  - Homes whose stored data source definition predates the field load it with the default.
  - The default is unchanged. A higher ratio (for example 0.9) would flag 2008-09-19, but also normal dips such as the day after a monthly expiration.
- **Open, for the owner's decision:**
  - **9.** *Flagged days* in the monthly coverage counts days with any quality flag, so in 2023 almost every day is flagged, because some contract has a zero ask most days. DATA-70 leaves the summary's form open; options are a count per check, or counting only the checks the owner considers significant.
- **Tests:** 282, all passing: 276 run by default (unit 243, contract 28, meta 3, packaging 2), plus the 6 real-data tests, which pass with `PROPHETOVOL_VENDOR_DATA` set (about 100 seconds together). Changed and new in `tests/unit/test_data_cli.py`:
  - the overlap wording, and dates instead of UTC instants
  - aligned columns and plurals
  - readable `--details` and parseable `--json`
  - coverage collapsing empty months
  - "No runs affected"
  - *Active days* after a delete
  - job targets
  - a closed output pipe exiting quietly, while other `OSError`s stay unexpected
  - in `tests/unit/test_ingest.py`: the low-count ratio, where an 80% day passes at the default, is flagged at 0.9 with the ratio in the description, and 1.5 is refused
- **M1 is complete.** Next: Phase 9 (spec model, validation and publishing), the start of M2.

# Options Backtester — Phase 1 Requirements Specification

Oct 25, 2026 · @Chuck · **Status: Draft for review (v2)** · Companion document: *Options Backtester — Project Plan & Roadmap (Draft)* ("the project plan"), which records the later phases and the reasoning behind decisions made here.

**Changes in v2:** daily, row-based names replaced by **snapshots** taken at **steps** with an **as-of** timestamp; time to expiry is a year fraction computed from timestamps, matching the vendor's convention; expiration selectors and conditions state their units (calendar days, trading days, or nth expiration); distribution-readiness constraints added (§16.2).

## 1. Overview & Scope

This document specifies **Phase 1**: a deterministic backtesting tool for index options, built on end-of-day option data in the ivolatility.com format. It is a local, single-user application: an installable Python package with a CLI and a browser front end served by a local HTTP API, following the architecture and stack of the data profiling tool (§4, §16).

In Phase 1 a user can:

1. **Load data:** upload raw ivolatility files, which are validated, normalized, versioned and stored as market snapshots. Data can be replaced or deleted by underlying and date range.
2. **Define strategies:** describe a multi-leg option structure and how it is managed (selection of expirations and strikes, entry schedule, roll and close triggers, delta hedging, sizing), through a form or YAML.
3. **Define stress tests:** underlying price slides, evaluated at every step of a backtest, either reporting only or gating new trades.
4. **Run backtests:** a strategy version over a date range, with a configuration (capital, fills, costs, stress mode), as a background job.
5. **Review results:** position, structure and portfolio snapshots (P&L and greeks) at every step, stress snapshots, events, and aggregate statistics, all traceable to exact data, strategy, configuration and software versions.

There is **no AI in Phase 1**. Later phases add an AI layer that, given a request or a statement, chooses what to test and drives this same deterministic tool. Phase 1 must therefore expose every capability through documented, schema-described service operations (§14), so that later an agent can use them exactly as a person does.

**Design priorities, in order:**

1. **Correct and traceable.** Every number is reproducible from recorded inputs, and every input is versioned. Position snapshots always reconcile to portfolio snapshots.
2. **Deterministic.** The same inputs produce identical results. There is no randomness in Phase 1.
3. **Point-in-time.** The engine can never read data stamped after the current step's as-of time.
4. **Frequency-neutral.** Phase 1 data is end of day, but nothing in the model assumes one step per day except the frequency setting itself.
5. **Extensible by plug-in.** Selectors, conditions, actions, hedge rules, sizing methods, fill models, settlement sources, stress scenario types and constructors are registries, so later phases add implementations without changing the engine (§5.4).
6. **Database-portable.** DuckDB only for now, designed so other databases can be added through adapters (§6.9).

## 2. Goals & Non-Goals

**Goals for Phase 1**

- Ingest, validation, versioning, replacement and deletion of ivolatility end-of-day option data, with a coverage view and quality reports.
- A strategy specification model covering the three example strategies in Appendix B, with validation that reports errors field by field.
- A deterministic step-by-step engine: selection, entries, triggers, rolls, expiration and settlement handling, delta-hedging bands, sizing, fills and costs.
- A stress module with an underlying-slide scenario type and three enforcement modes (Monitor, Scale to limit, Halt run).
- Position, structure and portfolio snapshots at every step, an events log, and aggregate statistics.
- A CLI, a documented HTTP API (OpenAPI), and a browser GUI covering every Phase 1 capability.
- Persisted background jobs with progress and cancellation; an audit trail of actor, channel, software versions and rejected attempts.
- A synthetic data generator producing ivolatility-format files, for tests and a demo.

**Non-goals for Phase 1** (see also §19)

- Any AI or LLM functionality, including the strategy-building chat.
- Market-context calculations, forecasts, conditions on market state, optimizers or any constructor other than the rules-based one.
- Stress scenarios other than underlying slides; risk limits other than maximum stress loss.
- Holding AM-settled contracts to expiration (no settlement-value source exists yet; §8.6).
- Data frequencies other than end of day.
- Equities and corporate actions; underlyings other than cash-settled European index options.
- Multiple users, remote deployment, databases other than DuckDB, and the protected trial build itself (§16.2 only keeps it possible).

## 3. Users & Primary Tasks

The primary user is an **options trader or researcher** who knows option structures, greeks and hedging, and is not necessarily comfortable with YAML or the command line.

| # | Task | Area |
| --- | --- | --- |
| T1 | "Load this year of SPX data." Upload a file, review the quality report, resolve any overlap with existing data. | Data |
| T2 | "What data do I have?" See coverage by underlying and date, with versions and quality flags. | Data |
| T3 | "Replace or remove this range." Replace a date range with a new file, or delete it. | Data |
| T4 | "Describe this strategy." Define legs, selection, entry, triggers, hedging and sizing; validate; publish a version. | Strategies |
| T5 | "Set up a stress test." Define an underlying slide and its loss limit. | Stress |
| T6 | "Run it." Choose a strategy version, date range, configuration and stress definition; check readiness; start the run. | Runs |
| T7 | "How did it do?" Read summary statistics, the equity curve and drawdowns, portfolio greeks and P&L over time. | Results |
| T8 | "What happened at this step?" Drill into one step's positions, trades, hedges, stress results and events. | Results |
| T9 | "Where did this number come from?" See the exact data versions, strategy version, configuration and software versions behind a run. | Results |

## 4. Architecture

```
browser (React + TypeScript SPA)
        │  HTTP/JSON (OpenAPI-documented REST API)
        ▼
optbt serve ── API server (FastAPI on uvicorn)
        │        ├─ job runner (persisted jobs, progress, cancellation)
        │        └─ static file serving for the built SPA
        ▼
BacktestService (single owner of all storage access)
   ├─ DataManager        ingest, validation, versions, replace/delete, coverage
   ├─ ReferenceData      underlyings, data sources, trading calendar, settlement sources
   ├─ CatalogRepository  strategy specs, stress definitions, runs, jobs, audit
   ├─ RunCoordinator     pre-flight, run lifecycle, recording
   │     └─ Engine (pure library: no I/O)
   │           ├─ Selectors / Conditions / Actions / Hedge / Sizing / Fills (registries)
   │           ├─ Pricer (Black-76)
   │           └─ StressEvaluator (scenario-type registry)
   └─ StorageAdapter (DuckDB implementation)  ── Ibis for reads
         ├─ catalog.duckdb   definitions, data-version registry, runs, jobs, audit
         ├─ results.duckdb   run output (snapshots, events, statistics)
         └─ market/          market snapshots as Parquet, partitioned by underlying and month
```

- **ARC-1** `BacktestService` is the only component that opens storage. The CLI and the API server are thin clients: they translate input to service calls and results to output, and contain no domain logic. Capabilities missing from the service are added to the service, not to a client.
- **ARC-2** The **engine is a pure library**. It receives a `MarketDataView`, a strategy specification, a run configuration and stress definitions, and returns results through a recorder interface. It performs no file, database or network access, so it can run in worker processes later (project plan, Phase 2) and be tested without storage.
- **ARC-3** **Point-in-time access.** The engine reads market data only through `MarketDataView`, which is bound to the current step's as-of timestamp and raises an error for any request stamped after it. This guard is enforced in code and covered by tests (§17).
- **ARC-4** **One writer.** DuckDB allows one read-write connection per file. The service owns the read-write connections; write jobs run one at a time; read requests are served during a running job through separate cursors (as in the profiling tool's GAP-8).
- **ARC-5** **Registries.** Every extensible component type is a registry of named implementations (§5.4). Each implementation declares a name, a description and a parameter schema. Specs and configurations refer to implementations by name.
- **ARC-6** **Single-user, local.** The server binds to `127.0.0.1` only, with the profiling tool's local security (§13.1). Remote deployment is out of scope.
- **ARC-7** **Product naming is provisional.** This document uses the working names *Options Backtester*, Python package `options_backtester`, CLI command `optbt`, and home directory `~/.optbt`. They are placeholders to be confirmed (§20).

## 5. Domain Model

### 5.1 Time: steps, snapshots and as-of

- **TIME-1** A run advances in **steps**. Each step has an **as-of** timestamp (timezone-aware) and a sequence number. The run's **frequency** is a configuration value; Phase 1 supports only `end_of_day`, with one step per trading day.
- **TIME-2** A **snapshot** is the complete state of something as of a step. Phase 1 has four kinds:
  - **Market snapshot:** the option chain and index level for one underlying as of a time (input).
  - **Position snapshot:** one security (an option contract or a hedge) held or traded at a step (output).
  - **Portfolio snapshot:** the whole run's totals at a step (output).
  - **Stress snapshot:** the stress P&L of the portfolio, and of each structure, under each scenario at a step (output).

  A **structure snapshot** (one structure's totals at a step) is a view derived from position snapshots.
- **TIME-3** **Time quantities are named by their units.** Fields and parameters say whether they mean calendar days, trading days, steps or years (for example `days_to_expiry`, `trading_days_held`, `stale_mark_warning_steps`). A bare "days" is not used where the meaning could differ with frequency.

### 5.2 Entities

| Entity | Identity | Versioned? | Summary |
| --- | --- | --- | --- |
| `Underlying` | `symbol` | Reference config | An index with its multiplier, exercise style, and per-root settlement style and expiry time (§7.1). Phase 1 ships `SPX`. |
| `DataSource` | `source_id` | Reference config | A data vendor format with its snapshot timing (§7.2). Phase 1 ships `ivolatility_eod`. |
| `DataImport` | `import_id` | Immutable | One uploaded file: hash, name, size, rows, underlying, as-of range, quality report, actor, channel, time. |
| `MarketSnapshot` | `(underlying, as_of)` | Via data versions | The chain and index level for one underlying as of a time. |
| `DataVersion` | `(underlying, as_of, import_id)` | Append-only | The market snapshot one import supplied for one underlying and as-of time. At most one version is *active* per `(underlying, as_of)`. |
| `StrategySpec` | `(spec_id, version)` | Immutable | A structure definition and its management rules (§8). |
| `StressDefinition` | `(stress_id, version)` | Immutable | A named set of stress scenarios with an optional loss limit (§10). |
| `Run` | `run_id` | Immutable once finished | One execution of a strategy version over a date range with a configuration (§11). |
| `Step` | `(run_id, step)` | — | One point in a run, with its as-of timestamp. |
| `Structure` | `(run_id, structure_id)` | — | One instance of a strategy's structure opened during a run, with its legs and hedge. |
| `Trade` | `(run_id, trade_id)` | — | One fill: an option leg or a hedge, opening or closing. |
| `PositionSnapshot` | `(run_id, step, position_key)` | — | One security held or traded at a step (§12.1). |
| `PortfolioSnapshot` | `(run_id, step)` | — | Portfolio totals at a step (§12.2). |
| `StressSnapshot` | `(run_id, step, stress_id, scenario_id, structure_id or portfolio)` | — | Stress P&L per scenario at a step (§10.6). |
| `RunEvent` | `(run_id, seq)` | — | Something that happened: an entry, roll, close, settlement, forced close, hedge, stress action or data issue (§12.3). |
| `Job` | `job_id` | Persisted | A background operation with status and progress (§13.3). |
| `Attempt` | `attempt_id` | Append-only | Every requested operation and its outcome, including rejections (§15). |

### 5.3 Versioning rules

- **VER-1** `StrategySpec` and `StressDefinition` are immutable once published. Every change publishes a new integer version per id; prior versions are kept. Identity is always `(id, version)` wherever traceability matters. Saving unchanged content publishes nothing and says so.
- **VER-2** Each published version stores a content hash of its canonical JSON form.
- **VER-3** A `Run` records, by reference, the strategy version, the stress definition versions, the full configuration (§11.1), the configuration's hash, and the list of `DataVersion`s it read. Because all of these are immutable, the reference alone reconstructs what ran.
- **VER-4** Market snapshots are versioned per `(underlying, as_of)` through `DataVersion` (§6.5).

### 5.4 Conventions

These meanings apply everywhere (specs, results, documentation). They are kept in one conventions module and are documented alongside the schemas (§14).

- **CONV-1** **Time to expiry** is the model input: a year fraction computed from timestamps, in calendar time:

  `time_to_expiry_years = (expiry_timestamp − as_of) / 365 days`

  computed to the minute. This matches the convention found in the vendor's greeks (§7.2). For people, it is also shown as fractional **calendar days to expiry** (`days_to_expiry = time_to_expiry_years × 365`), so a one-day PM-settled weekly at the 16:15 snapshot shows 0.99 days, not 1.
- **CONV-2** **Trading days to expiry** is the number of trading days after the as-of date, up to and including the expiration date. It is used where a rule is stated in trading days.
- **CONV-3** **Expiry timestamps** come from the underlying's root configuration: for SPX, 09:30 ET on the expiration date for AM-settled roots and 16:00 ET for PM-settled roots (§7.1).
- **CONV-4** **Delta targets are absolute values.** "A 25-delta put" means a put whose delta is −0.25; a spec writes `target: 0.25` for both calls and puts.
- **CONV-5** **At the money** means the 50-delta option of the leg's own type (call or put), not the strike nearest to spot. The strike nearest the series forward is available as a separate selector (§8.3).
- **CONV-6** **Trades execute at the step** at which the triggering condition is observed. For end-of-day data, that is the close.
- **CONV-7** **Dollar greeks**, with `q` the signed quantity in contracts, `m` the multiplier and `S` the index level:
  - dollar delta = Δ · q · m · S (equivalent index exposure)
  - dollar gamma = Γ · q · m · S² · 0.01 (change in dollar delta for a 1% index move)
  - dollar vega = vega · q · m (per one volatility point; vendor vega is per point)
  - dollar theta = θ · q · m (per calendar day; vendor theta is per calendar day)
- **CONV-8** **Signs:** positive quantity is long; positive cash flow is cash received.
- **CONV-9** **A roll**, unless the spec says otherwise, closes the structure and re-establishes it using the original selection rules.

### 5.5 Registries (plug-in points)

- **REG-1** The following component types are registries. Phase 1 ships the implementations listed; later phases add more without engine changes.

| Registry | Phase 1 implementations | Section |
| --- | --- | --- |
| Expiration selectors | `target_days`, `trading_days_out`, `nth_expiration`, `same_as_leg`, `next_after_leg` | §8.2 |
| Strike selectors | `delta`, `atm`, `forward`, `same_strike_as`, `strike_offset` | §8.3 |
| Entry schedules | `once`, `when_flat`, `every_n_trading_days`, `weekdays` | §8.4 |
| Trigger conditions | `leg_abs_delta_above`, `leg_abs_delta_below`, `leg_days_to_expiry_at_or_below`, `structure_min_days_to_expiry_at_or_below`, `structure_pnl_pct_at_or_above`, `structure_pnl_pct_at_or_below`, `trading_days_held_at_least` | §8.5 |
| Trigger actions | `close`, `roll` | §8.5 |
| Hedge rules | `none`, `band` | §8.7 |
| Sizing methods | `contracts`, `notional` | §8.8 |
| Fill models | `mid`, `cross_spread`, `mid_plus_fraction` | §9.5 |
| Settlement sources | `pm_index_close` (PM-settled: index close at expiry) | §7.4 |
| Stress scenario types | `underlying_slide` | §10.2 |
| Stress failure modes | `monitor`, `scale_to_limit`, `halt_run` | §10.4 |
| Constructors | `rules` (applies a `StrategySpec`) | §9.1 |

- **REG-2** Every implementation declares a **name**, a **one-paragraph description**, a **pydantic parameter model** with a description on every field, and the **version** of its implementation. The version is recorded on runs.
- **REG-3** Registries are discoverable through the service, the API and the CLI (`optbt registry list`, `optbt registry show <type> <name>`), returning the descriptions and JSON Schemas. This is what the GUI forms and, later, an agent read (§14).
- **REG-4** Condition types are pluggable so that later phases can add conditions on market context and forecasts, written by people or defined by an agent. Phase 1 conditions read only the structure's own state and the calendar.

## 6. Data Module

### 6.1 Input format

- **DATA-1** The input is the ivolatility end-of-day option CSV with these 22 columns, in this order, with a header row. Mapping to the normalized schema is in Appendix A.

  `symbol, exchange, date, adjusted close, option symbol, expiration, strike, call/put, style, ask, bid, mean price, iv, volume, open interest, stock price for iv, *, delta, vega, gamma, theta, rho`

- **DATA-2** Dates in `date` and `expiration` are `MM/DD/YYYY`. The column named `*` is a flag that is either empty or `*`.
- **DATA-3** One file may contain several dates and one underlying. A file with more than one value of `symbol` is rejected.
- **DATA-4** Accepted uploads are `.csv` files and `.zip` archives containing one or more such CSVs. The maximum uncompressed size per import is configurable, default 2 GB. (A year of SPX is roughly 750 MB of CSV.)

### 6.2 Upload & ingest

- **DATA-10** Upload streams the file to a temporary file on the server; it is never held whole in memory. Ingest runs as a background job (§13.3) with progress reported as rows and dates processed.
- **DATA-11** Ingest parses, validates (§6.3) and normalizes the rows into market snapshots, then writes them to Parquet partitioned by underlying and month (§6.9) under a new `import_id`. Nothing becomes visible to runs until the user commits the import (§6.4).
- **DATA-12** The file's SHA-256 hash is recorded. Uploading a file whose hash matches an existing import is reported to the user, who may cancel.
- **DATA-13** **Normalization rules:**
  - **Timestamps.** Each vendor `date` becomes a snapshot as-of timestamp using the data source's timing (§7.2): for `ivolatility_eod`, option quotes, IV, greeks and the forward are as of 16:15 ET, and the index level is as of 16:00 ET. Both times are stored.
  - **Expiry timestamp.** Each contract's `expiry_timestamp` is its expiration date at the expiry time of its root (CONV-3).
  - `iv` of `-1` is stored as null.
  - Greeks are stored as given, except that on a contract's expiration date all greeks and `iv` are stored as null. The vendor reports them as 0 and −1 on that day, and they must not be used.
  - `root` is parsed from the option symbol (the characters before the date, trimmed): for SPX data, `SPX` or `SPXW`.
  - `settlement_style` (`AM` or `PM`) is derived from `root` using the underlying's root configuration (§7.1). A root with no configuration is an error.
  - `vendor_mid` keeps the vendor's `mean price` as given. The engine computes its own mid from bid and ask (§9.3) and never uses `vendor_mid` for pricing, because the vendor shows 0 when the bid is 0.
  - `forward` keeps `stock price for iv`, the vendor's per-series forward (each expiration has its own, since index futures exist only quarterly). It is ignored on a series' expiration date (§9.3).
  - `vendor_flag` is `true` where the `*` column is `*`. Its meaning is not yet confirmed; it is stored and displayed, and drives no behavior in Phase 1 (§20).

### 6.3 Validation & quality report

- **DATA-20** Validation produces a **quality report** stored with the import: counts and examples per check, per date. Errors block the import; warnings do not.

| Check | Severity |
| --- | --- |
| Required columns missing or misnamed | Error |
| Unparseable value in a required field (date, strike, expiration, call/put, bid, ask) | Error |
| Duplicate `(date, option symbol)` within the file | Error |
| More than one underlying in the file | Error |
| Unknown option root for the underlying | Error |
| `style` other than `E` | Error (Phase 1 supports European options only) |
| Crossed quote (bid > ask) | Warning |
| Zero ask, or zero bid and ask | Warning |
| `iv` of −1 on a date other than the contract's expiration | Warning |
| Missing `forward` | Warning |
| A trading day in the file's date range missing from the file (per the trading calendar, §7.3) | Warning |
| A date not in the trading calendar (a holiday or weekend) | Warning |
| Contracts for a date far below that date's neighbors (configurable ratio, default below 50% of the median of the 5 surrounding dates) | Warning |
| `vendor_flag` set | Count only (informational) |

- **DATA-21** The quality report is viewable in the GUI and the CLI, and is kept with the import permanently.

### 6.4 Overlap & commit

- **DATA-30** Before commit, the service compares the import's `(underlying, as_of)` set with the currently active data and shows the **overlap**: which snapshots already have active data, from which imports, with contract counts for each.
- **DATA-31** The user chooses one of:
  - **Replace overlapping dates:** the import's snapshots become active for every as-of it covers.
  - **Add new dates only:** the import's snapshots become active only where no active data exists; its overlapping snapshots are kept but not activated.
  - **Cancel:** nothing is activated and the staged data is discarded.
- **DATA-32** Commit is atomic: either every activation in the choice succeeds or none does.
- **DATA-33** Committing or replacing data queues the invalidation step (§6.7).

### 6.5 Data versions

- **DATA-40** Every `(underlying, as_of)` has at most one active `DataVersion`. Replaced versions are kept as *superseded* until purged (§6.6), so a past run can still identify exactly what it read.
- **DATA-41** The data-version registry lives in `catalog.duckdb`; snapshot contents live in Parquet. A version's identity is `(underlying, as_of, import_id)`.

### 6.6 Delete & purge

- **DATA-50** **Delete** by underlying and date range deactivates the active versions in the range. The data is kept until purged.
- **DATA-51** **Purge** physically removes superseded or deleted data (by import, or by underlying and date range) and reclaims disk space.
- **DATA-52** Before a delete or purge, the service lists the runs that read the affected versions. The user must confirm. After a delete or purge, those runs are flagged *data superseded* (§11.5); their results are kept.
- **DATA-53** Delete and purge are recorded in the audit trail (§15).

### 6.7 Invalidation

- **DATA-60** When active data changes for a date range (commit, replace, delete), every completed run that read a changed version is flagged *data superseded*, with the affected dates. Runs are never recalculated automatically; the user re-runs to get a new run.
- **DATA-61** The flag is visible on run lists and run pages, and returned by the API.

### 6.8 Coverage view

- **DATA-70** For each underlying, the coverage view shows each trading day in the calendar with: whether an active snapshot exists, its import, its contract count and its quality flags. In the GUI this is a calendar heatmap with drill-down to a date; in the CLI it is a table summarized by month.

### 6.9 Storage layout & portability

- **DATA-80** Market snapshots are stored as Parquet under `market/underlying=<SYMBOL>/year=<YYYY>/month=<MM>/`, one file per import per partition, read through DuckDB. Active-version filtering joins against the data-version registry.
- **DATA-81** **Reads go through Ibis.** All engine-facing and service queries over market data, the catalog and results are written as Ibis expressions, not DuckDB SQL, so they can run on another back end later.
- **DATA-82** **Writes go through a `StorageAdapter` interface**, because bulk loading, activation, deletion, purging and transactions differ by database. The interface has at least: `stage_import`, `commit_import(choice)`, `discard_import`, `deactivate_range`, `purge`, `write_run_results(atomic)`, `open_market_view(underlying, as_of)`, and catalog CRUD for definitions, runs, jobs and attempts. Phase 1 has one implementation: DuckDB plus Parquet.
- **DATA-83** Physical layout (files, partitions, rows) is known only to the adapter. Everything above it works in underlyings, as-of times, snapshots and data versions.
- **DATA-84** An **adapter contract test suite** exercises every interface operation against expected results: load, overlap, replace, add-new-only, delete, purge, point-in-time reads, and atomic run writes. Every adapter must pass it.

## 7. Reference Data

### 7.1 Underlyings

- **REF-1** An underlying's configuration holds: symbol, description, contract multiplier, exercise style, the exchange time zone, and, per option root, the settlement style and expiry time. Phase 1 ships:

  ```yaml
  symbol: SPX
  multiplier: 100
  exercise_style: european
  timezone: America/New_York
  roots:
    SPX:  {settlement_style: AM, expiry_time: "09:30"}
    SPXW: {settlement_style: PM, expiry_time: "16:00"}
  ```

- **REF-2** Underlying configurations are editable through the service (as versioned definitions), so another index (for example NDX or RUT) can be added by configuration.

### 7.2 Data sources

- **REF-5** A data source's configuration holds its format and its snapshot timing. Phase 1 ships:

  ```yaml
  source_id: ivolatility_eod
  frequency: end_of_day
  timezone: America/New_York
  option_snapshot_time: "16:15"   # quotes, IV, greeks, forward
  index_snapshot_time:  "16:00"   # adjusted close
  time_to_expiry_convention: act_365_to_minute
  ```

- **REF-6** The timing was inferred from the sample files: solving the vendor's vega for time to expiry, at the vendor's IV and forward, gives calendar time over 365 days, short of whole days by 15 minutes for PM-settled series and by about 6¾ hours for AM-settled series, at every maturity tested. That matches a 16:15 ET snapshot with expiries at 16:00 and 09:30 ET. This is to be confirmed with the vendor (§20). The configuration, not code, holds these values.

### 7.3 Trading calendar

- **REF-10** The trading calendar is the NYSE calendar from the `exchange_calendars` package (`XNYS`). It defines trading days for coverage, pre-flight checks, trading-day schedules, trading days to expiry and trading days held.
- **REF-11** The calendar version (the package version) is recorded on runs.

### 7.4 Settlement sources

- **REF-20** Settlement is resolved through the settlement-source registry by settlement style. Phase 1 ships one source, `pm_index_close`, which settles PM-settled contracts at intrinsic value against the index level at expiry (the `adjusted close` on the expiration date).
- **REF-21** No settlement source exists for AM-settled contracts in Phase 1, because the vendor data contains no AM settlement value (SET) and the vendor does not supply one. AM-settled contracts are therefore never held to expiration (§8.6). A future source that loads SET values from a user-uploaded table plugs in here without engine changes (project plan).

## 8. Strategy Specification

### 8.1 Structure

- **SPEC-1** A `StrategySpec` contains:
  - `id`, `description`
  - `underlying` (symbol)
  - `legs`: an ordered list of legs
  - `entry`: an entry schedule (§8.4)
  - `triggers`: a list of triggers (§8.5)
  - `expiry_handling`: what happens when a leg settles or is force-closed (§8.6)
  - `hedge`: a hedge rule (§8.7)
  - `sizing`: a sizing method (§8.8)
  - `selection`: quote filters for selection (SPEC-28)
- **SPEC-2** Each **leg** has:
  - `id` (unique within the spec)
  - `option_type`: `call` or `put`
  - `side`: `long` or `short`
  - `ratio`: a positive integer (contracts of this leg per unit of the structure)
  - `expiration`: an expiration selector
  - `strike`: a strike selector
  - `roots`: optional list of allowed option roots (default: all roots of the underlying)
  - `hold_to_expiration`: boolean, default `false` (§8.6)
- **SPEC-3** Legs may refer to other legs (by `id`) in their selectors. References must form no cycle. Legs are resolved in dependency order.
- **SPEC-4** **Selection is atomic.** If any leg cannot be selected at a step, the structure is not opened at that step, and an event records which leg failed and why.

### 8.2 Expiration selectors

- **SPEC-10** `target_days`: choose the expiration whose calendar days to expiry (CONV-1, fractional) is nearest `days`.
  - Parameters: `days`; `min_days` and `max_days` (defaults `days − 10` and `days + 10`, floored at 0); `tie_break`: `later` (default) or `earlier`; `filter` (SPEC-14).
  - Expirations outside `[min_days, max_days]` are not eligible.
  - Example: `days: 45` for a monthly-style strategy; `days: 0.5, max_days: 1` for a same-day (0DTE) strategy.
- **SPEC-11** `trading_days_out`: choose the expiration whose trading days to expiry (CONV-2) equals `n`, or the nearest within `tolerance` trading days (default 0). Parameters: `n`, `tolerance`, `tie_break`, `filter`. Example: `n: 1` for the next trading day's expiration.
- **SPEC-12** `nth_expiration`: the `n`-th eligible expiration after the as-of time, counting only expirations that pass `filter` (`n: 1` is the next one). Parameters: `n`, `filter`. Example: `n: 2` with `standard_monthly_only` for the second monthly.
- **SPEC-13** `same_as_leg`: the same expiration as the referenced leg. Parameter: `leg`. `next_after_leg`: the first eligible expiration strictly after the referenced leg's. Parameters: `leg`, `filter`.
- **SPEC-14** **Expiration filters** (for every selector that takes `filter`):
  - `standard_monthly_only`: only the standard monthly expiration (third Friday, or the exchange-adjusted date)
  - `weekdays`: allowed weekdays of the expiration date (for example `[FRI]`)
  - `roots`: allowed option roots
  - `settlement_styles`: `AM`, `PM`, or both
- **SPEC-15** An expiration is never eligible at or after its expiry timestamp, and an AM-settled expiration is never eligible on or after its last trading day (the trading day before the expiration date).

### 8.3 Strike selectors

- **SPEC-20** `delta`: the strike in the chosen expiration whose absolute delta is nearest `target` (CONV-4).
  - Parameters: `target`; `tolerance` (default 0.05 absolute delta; outside it, no match); `tie_break`: `further_otm` (default) or `nearer_otm`.
- **SPEC-21** `atm`: equivalent to `delta` with `target: 0.50` (CONV-5).
- **SPEC-22** `forward`: the strike nearest the series forward (the vendor's `stock price for iv` for that expiration). Parameter: `tolerance_points` (default: the series' strike spacing).
- **SPEC-23** `same_strike_as`: the referenced leg's strike, which must be listed in this leg's expiration. Parameters: `leg`; `tolerance_points` (default 0, meaning exactly the same strike).
- **SPEC-24** `strike_offset`: the referenced leg's strike plus an offset, choosing the nearest listed strike. Parameters: `leg`; `points` or `percent` (one of them, signed); `tolerance_points` (default: the series' strike spacing).
- **SPEC-25** **No match.** When a selector finds no eligible contract within tolerance, the outcome follows `on_no_match`: `skip_entry` (default) or `nearest_any` (the nearest eligible contract regardless of tolerance, with a warning event).
- **SPEC-26** Selection uses only contracts eligible under §8.2 and under the quote filters (SPEC-28).
- **SPEC-27** Delta-based selection uses the vendor's delta at that step. Contracts with a null delta are not eligible for delta-based selectors.
- **SPEC-28** **Quote filters** (spec-level `selection` block, applying to all legs):
  - `require_valid_quote` (default `true`; §9.3)
  - `min_bid` (default 0.05)
  - `min_open_interest` (default 0, meaning no filter)
  - `exclude_vendor_flagged` (default `false`; the `*` flag's meaning is unconfirmed)

### 8.4 Entry schedules

- **SPEC-30** `once`: open one structure at the first step of the run.
- **SPEC-31** `when_flat`: open a structure at any step when no structure of this spec is open.
  - Parameter: `cooldown_trading_days`, the number of trading days to wait after a structure is closed by a `close` action or by expiry before re-entering. Default 1, so a close and a re-entry don't happen at the same step; a `roll` re-establishes immediately regardless.
- **SPEC-32** `every_n_trading_days`: open a structure every `n` trading days from the start of the run.
- **SPEC-33** `weekdays`: open a structure on the listed weekdays. Parameter: `holiday_shift`: `next` (the next trading day) or `skip` (default).
- **SPEC-34** All schedules except `once` take `max_open` (default 1): no entry occurs while `max_open` structures of this spec are open.
- **SPEC-35** An entry that fails selection (SPEC-4) is retried at the next scheduled step; it is not queued.

### 8.5 Triggers

- **SPEC-40** A trigger has:
  - `name`
  - `scope`: `{leg: <id>}` or `structure`
  - `action`: `close` or `roll`
  - `any_of`: a list of conditions, any one of which fires the trigger
- **SPEC-41** **Phase 1 conditions:**

| Condition | Parameters | Fires when |
| --- | --- | --- |
| `leg_abs_delta_above` | `leg`, `threshold` | \|delta\| of the leg's contract > threshold |
| `leg_abs_delta_below` | `leg`, `threshold` | \|delta\| < threshold |
| `leg_days_to_expiry_at_or_below` | `leg`, `days`, `unit` | the leg's time to expiry ≤ `days`, measured in `unit`: `calendar_days` (default, fractional, CONV-1) or `trading_days` (CONV-2) |
| `structure_min_days_to_expiry_at_or_below` | `days`, `unit` | the shortest time to expiry among open legs ≤ `days`, in `unit` |
| `structure_pnl_pct_at_or_above` | `percent` | structure P&L since entry, as a percentage of the absolute entry premium, ≥ percent (a profit target) |
| `structure_pnl_pct_at_or_below` | `percent` (negative) | that percentage ≤ percent (a stop) |
| `trading_days_held_at_least` | `days` | trading days since the structure was opened ≥ days |

- **SPEC-42** Conditions are evaluated at each step on that step's marks and vendor greeks. A condition that needs a null greek evaluates to false and records a warning event.
- **SPEC-43** **Actions:**
  - `close` with leg scope closes that leg; the structure stays open with its remaining legs. `close` with structure scope closes every leg and the structure's hedge.
  - `roll` with leg scope closes the leg and re-selects it with its original selectors; references to other legs use those legs' current contracts. The leg's quantity is unchanged.
  - `roll` with structure scope closes the structure and opens a new one with the spec's selectors and sizing (CONV-9). The new structure records the old one as its parent.
- **SPEC-44** **One action per structure per step.** When several triggers fire at the same step, precedence is: structure `close`, then structure `roll`, then leg `close`, then leg `roll` (in the triggers' listed order within each). The chosen action and every other fired trigger are recorded in the event.
- **SPEC-45** A roll whose opening side fails selection leaves the structure closed (for a structure roll) or the leg closed (for a leg roll), and records the failure.

### 8.6 Expiration & settlement

- **SPEC-50** **PM-settled legs** held to their expiry settle at intrinsic value against the index level at expiry (`pm_index_close`, REF-20). Settlement is a cash flow with no fill-model cost.
- **SPEC-51** **AM-settled legs are force-closed** at the last step of their last trading day (the trading day before the expiration date) through the fill model, as an ordinary closing trade, with a `forced_close_am` event. This applies whether or not any trigger would have fired.
- **SPEC-52** **Validation rejects** a leg with `hold_to_expiration: true` whose allowed roots include an AM-settled root, with the message: *"AM-settled contracts cannot be held to expiration: no AM settlement source is configured. Restrict this leg to PM-settled roots, or add a closing trigger."*
- **SPEC-53** **Validation warns** when a leg can select an AM-settled root and no trigger would close it before its last trading day (no `leg_days_to_expiry_at_or_below` or `structure_min_days_to_expiry_at_or_below` that fires at least one trading day before expiry). The warning explains that the engine will force-close the leg.
- **SPEC-54** `expiry_handling` sets what happens to the rest of the structure when a leg settles or is force-closed:
  - `close_structure` (default): close the remaining legs and the hedge at the same step.
  - `keep_remaining`: keep the remaining legs open.
  - `roll_leg`: re-select the expired leg as a leg roll.

### 8.7 Delta hedging

- **SPEC-60** `none`: no hedging.
- **SPEC-61** `band`: keep the structure's net delta per unit within a band.
  - Parameters: `lower`, `upper`, `target` (with `lower ≤ target ≤ upper`); `scope`: `structure` (Phase 1 only).
  - **Measure.** With `N` structure units, leg quantities `q_i` (signed contracts), vendor deltas `δ_i`, hedge holding `h` in index units and multiplier `m`:

    net delta per unit = ( Σ q_i · δ_i + h / m ) / N

    It is expressed in deltas per one unit of the structure. For example, `0.03` is long 3 deltas per spread.
  - If the measure is outside `[lower, upper]` after the step's option trades, the hedge is traded so the measure equals `target`.
  - Hedging to flat at every step is `lower = upper = target = 0`.
- **SPEC-62** **The hedge instrument** in Phase 1 is a synthetic position in the index itself, traded at the index level in the snapshot, with a configurable cost in basis points of traded notional (§11.1). Financing, dividends and margin on the hedge are not modeled (§18). Futures and ETF hedges are later work.
- **SPEC-63** Hedging is evaluated at every step after option trades (§9.1, step 8), using that step's vendor deltas. Legs with a null delta (at expiry) count as zero delta after settlement.
- **SPEC-64** When a structure closes, its hedge is closed at the same step.

### 8.8 Sizing

- **SPEC-70** `contracts`: open `quantity` units of the structure per entry; leg *i* trades `quantity × ratio_i` contracts.
- **SPEC-71** `notional`: units = `notional / (S × m)`, where `S` is the index level at the entry step.
- **SPEC-72** Rounding follows the run configuration (§11.1): `whole` (round down; if below 1, the entry is skipped with an event) or `fractional`.
- **SPEC-73** A structure roll re-sizes using the sizing method at the roll step; a leg roll keeps the leg's quantity.

### 8.9 Validation & authoring

- **SPEC-80** Validation is available as a **dry run** that publishes nothing. It returns structured errors and warnings, each with a field path and a message, and is the same validation that publishing applies. Checks include schema validity, references to existing legs, no reference cycles, consistent hedge band bounds, known registry names with valid parameters, explicit units on time parameters, and SPEC-52 and SPEC-53.
- **SPEC-81** Specs can be authored in the GUI form editor (§13.4), or as YAML or JSON files imported through the CLI, the API or the GUI. Every spec version can be exported as YAML in the format import accepts, and an export round-trips exactly.
- **SPEC-82** The three example strategies in Appendix B ship as sample specs and are used as acceptance tests (§17).

## 9. Engine

### 9.1 Step loop

- **ENG-1** A run steps through every trading day in its date range at the configured frequency (one end-of-day step per trading day in Phase 1). At each step *t* the engine performs, in this order:

  1. **Open the view.** Bind `MarketDataView` to *t*'s as-of timestamp.
  2. **Settle.** Settle PM-settled legs whose expiry is at or before *t* (SPEC-50).
  3. **Mark.** Mark every open position (§9.3).
  4. **Evaluate triggers** for each open structure (§8.5), producing at most one action each.
  5. **Forced closes.** Add closes for AM-settled legs whose last trading day is *t*'s date (SPEC-51), and apply `expiry_handling` (SPEC-54).
  6. **Evaluate entries** under the entry schedule (§8.4) and build orders for new structures and for the opening sides of rolls.
  7. **Stress gate.** Size the opening orders (§8.8), then apply the stress mode to them (§10.4). Closing orders are never gated.
  8. **Execute and hedge.** Fill all orders at *t* (§9.5), then rebalance hedges (§8.7).
  9. **Record.** Compute and record position snapshots, the portfolio snapshot, stress snapshots and events (§12).

- **ENG-2** The **constructor** is the component that produces orders in steps 4 to 6. Phase 1 has one, `rules`, which applies a `StrategySpec`. The constructor interface takes the step's view, the current book and the spec or policy, and returns orders with reasons, so later constructors (an agent, an optimizer) plug in without changing the other steps.
- **ENG-3** A run may hold several structures of one spec at once (SPEC-34). Each structure is tracked separately with its own legs, hedge and P&L.
- **ENG-4** Every time-dependent calculation (time to expiry, trading days to expiry, trading days held) is computed from timestamps and the trading calendar, never from step counts, so a later intraday frequency changes no rule's meaning.

### 9.2 Determinism

- **ENG-10** Given the same strategy version, configuration, stress definitions, data versions and software versions, a run produces identical results. The engine uses no randomness, no wall-clock time and no unordered iteration that affects output.

### 9.3 Quotes, marks & prices

- **ENG-20** A quote is **valid** when `ask > 0`, `bid ≥ 0` and `ask ≥ bid`. The mid is `(bid + ask) / 2`.
- **ENG-21** **Marking.** A position is marked at the mid of its valid quote. If the quote is invalid or the contract is absent from the market snapshot, the last valid mark is carried forward, the position snapshot is flagged `stale_mark`, and a data-issue event is recorded. After a configurable number of consecutive stale steps (`stale_mark_warning_steps`, default 5), a warning event is recorded at each further stale step.
- **ENG-22** **Settled and force-closed legs** take their settlement value or fill price as the final mark.
- **ENG-23** **The series forward** (`stock price for iv`) is used for the `forward` selector and for stress pricing (§10.3). It is ignored on a series' expiration date.
- **ENG-24** **Greeks** are the vendor's values at the step. The engine computes greeks itself only for stress pricing (§10.3).
- **ENG-25** **Two times in one snapshot.** For `ivolatility_eod`, option marks are as of 16:15 ET and the index level as of 16:00 ET. In Phase 1 the hedge trades at the 16:00 index level while options trade at 16:15 quotes. This is a documented simplification (§18), not modeled.

### 9.4 Accounting

- **ENG-30** For each security (option contract or hedge) at step *t*, with signed quantity `q`, mark `P_t`, multiplier `m` (1 for the hedge, whose price is the index level), and that step's cash flows `CF_t`:
  - market value: `MV_t = q · P_t · m`
  - cash flow of a trade of `Δq` at fill price `F`: `−Δq · F · m − fees`
  - settlement cash flow: `q · settlement_value · m`, after which the position's quantity is 0
  - **period P&L** (since the previous step) = `MV_t − MV_{t−1} + CF_t`. A position opened at *t* has `MV_{t−1} = 0`; a position closed or settled at *t* has `MV_t = 0`.
- **ENG-31** Fees are reported separately as well as included in the P&L.
- **ENG-32** **Equity** at *t* = run capital + cumulative P&L. Interest on cash and margin financing are not modeled (§18).
- **ENG-33** **Invariants**, checked at the end of every run (and in tests, §17):
  - each portfolio snapshot's P&L and dollar greeks equal the sum of that step's position snapshots
  - cumulative P&L equals the sum of period P&L
  - the sum of all cash flows plus the final market value equals the final cumulative P&L

  A violated invariant fails the run with a diagnostic.

### 9.5 Fills & costs

- **ENG-40** Fill models:
  - `mid`: fill at the mid
  - `cross_spread`: buy at the ask, sell at the bid
  - `mid_plus_fraction`: fill at the mid plus `fraction` of the half-spread against the trader (`fraction` from 0 to 1)
- **ENG-41** An order for a contract with an invalid quote at *t* is not filled. Opening orders are dropped with an event. Closing orders are retried at the next step with a valid quote, and the position keeps its stale mark meanwhile, with events recorded.
- **ENG-42** Commission is a configurable amount per contract per side. Hedge cost is a configurable number of basis points of traded notional.
- **ENG-43** Opening trades at a price worse than the mid show a first-step loss against the mid mark; this is the intended way transaction cost becomes visible.

## 10. Stress Module

### 10.1 Stress definitions

- **STR-1** A `StressDefinition` is a named, versioned entity (VER-1) containing:
  - a list of **scenarios**, each with an `id`, a scenario `type` from the scenario-type registry, and that type's parameters
  - an optional **loss limit**: `max_loss_amount` (dollars) or `max_loss_pct_of_capital`, applied to the worst scenario
- **STR-2** A run attaches zero or more stress definitions. Each attached definition is evaluated at every step.

### 10.2 Scenario type: underlying slide

- **STR-10** `underlying_slide` shocks the index by each of a list of percentage moves, instantaneously, with each contract keeping its own implied vol (sticky strike) and with no time decay.
  - Parameter: `moves_pct`, a list of signed percentages.
  - Default definition, shipped as `default_slide`: `[-20, -15, -10, -5, 5, 10, 15, 20]`, with no loss limit.
- **STR-11** The scenario-type registry is the extension point for vol shocks, surface changes, joint scenarios and historical replays (project plan). Adding a type requires no engine change.

### 10.3 Revaluation

- **STR-20** Each option is revalued with **Black-76** on the series forward:

  `V = D · [F·N(d1) − K·N(d2)]` for calls and `V = D · [K·N(−d2) − F·N(−d1)]` for puts,

  where `d1 = (ln(F/K) + σ²T/2) / (σ√T)`, `d2 = d1 − σ√T`, `σ` is the contract's vendor implied vol, `T` is `time_to_expiry_years` (CONV-1), and `D = exp(−rT)` with `r` from the run configuration (default 0).
- **STR-21** Under a move of `s`, the forward becomes `F · (1 + s)` and `σ` is unchanged.
- **STR-22** **Stress P&L** for a position is `q · m · (V_shocked − V_base)`, with both values from the same model, so the model's level never mixes with market marks. The hedge's stress P&L is `h · S · s`.
- **STR-23** A contract with a null implied vol is revalued at intrinsic value in both base and shocked states, and flagged.

### 10.4 Enforcement modes

- **STR-30** The run configuration sets one stress mode (§11.1):

| Mode | Behavior |
| --- | --- |
| **Monitor** | Stress is computed and reported at every step; it never affects trades. Steps at which a gated mode would have acted are flagged, with what it would have done. |
| **Scale to limit** | Each step's opening orders are reduced to the largest size at which the post-trade book stays within every attached limit. If no size passes, the orders are skipped. Either way an event is recorded. |
| **Halt run** | If the step's opening orders would breach any attached limit, those orders are not executed; the step's closing orders and hedges are executed and recorded; then the run ends with status `halted`, recording the scenario, the loss and the limit. |

- **STR-31** Only **opening orders** are gated: entries and the opening sides of rolls. Closing orders and hedge trades are never gated.
- **STR-32** **The checked book** is the post-trade book, including the hedge the new orders would require under the spec's hedge rule (computed as hedging the new orders to the band's `target`). This keeps fully hedged strategies from being judged on their unhedged option legs.
- **STR-33** **Scale to limit** has an exact solution, because stress P&L is linear in the order size. With `L_s` the loss of the current book in scenario *s*, `ℓ_s` the loss per unit of the orders (hedge included), limit `X` and requested size `Q`:

  `q_max = min( Q, min over s with ℓ_s > 0 of (X − L_s) / ℓ_s )`

  Under `whole` rounding, `q_max` is rounded down to a whole unit. If `q_max ≤ 0`, the orders are skipped.
- **STR-34** **Breaches with no trade.** If the existing book exceeds a limit at a step with no opening orders (because the market moved), the breach is reported and flagged; no reduction is forced in Phase 1.
- **STR-35** With several stress definitions attached, an order must pass all of their limits. Definitions without limits are reported only.

### 10.5 Documentation of modes

- **STR-40** The three modes, their exact rules (STR-30 to STR-35) and their parameters are part of the configuration schema's descriptions (§14), so a later AI layer can choose the mode for a test from the documentation alone.

### 10.6 Stress snapshots

- **STR-50** At each step, for each attached definition and scenario: the portfolio's stress P&L, and the worst scenario and its loss.
- **STR-51** For each run: the maximum stress loss and its step, as-of time and scenario; the number of breach steps; and the number of scaled, skipped or would-have-acted steps.
- **STR-52** The stress P&L of each structure (not only the portfolio) is computed and stored, so the GUI can show which structure drives the worst case.

## 11. Runs

### 11.1 Run configuration

- **RUN-1** A run is defined by a strategy version, a configuration and zero or more stress definition versions. The configuration contains:

| Field | Default | Notes |
| --- | --- | --- |
| `underlying` | from the spec | |
| `data_source` | `ivolatility_eod` | determines snapshot timing (§7.2) |
| `frequency` | `end_of_day` | the only value in Phase 1 |
| `start_date`, `end_date` | required | trading days within this range |
| `capital` | required | used for equity, returns and percentage limits |
| `fill_model` | `cross_spread` | with `fraction` for `mid_plus_fraction` |
| `commission_per_contract` | 0.00 | per side; set to your all-in broker and exchange fee |
| `hedge_cost_bps` | 0.0 | basis points of traded hedge notional |
| `rounding` | `whole` | `whole` or `fractional` |
| `stress_mode` | `monitor` | `monitor`, `scale_to_limit`, `halt_run` |
| `stress_discount_rate` | 0.0 | `r` in STR-20 |
| `stale_mark_warning_steps` | 5 | ENG-21 |
| `allow_missing_days` | `false` | §11.2 |
| `label`, `notes` | empty | free text for the user |

- **RUN-2** Configurations can be saved as named templates and reused. The run itself always stores the full resolved configuration and its hash (VER-3).

### 11.2 Pre-flight

- **RUN-10** Before a run starts, a **pre-flight check** over the whole date range verifies:
  - the spec version and stress definitions validate
  - every trading day in the range has an active market snapshot for the underlying
  - each snapshot's chain is non-empty and has the fields the spec's selectors require
  - the configuration is valid
- **RUN-11** Pre-flight returns all problems at once. Missing trading days block the run unless `allow_missing_days` is `true`, in which case those days are skipped and the next step's snapshots are flagged. Other errors always block; warnings never do.
- **RUN-12** Pre-flight is available on its own (a readiness check) without starting a run.

### 11.3 Lifecycle

- **RUN-20** Statuses: `queued` → `running` → `completed` | `failed` | `halted` | `cancelled`.
  - `halted` means a stress limit stopped the run (STR-30).
  - Runs left `queued` or `running` by a previous process are marked `failed` with the reason `interrupted` when the catalog is next opened.
- **RUN-21** Progress is reported as steps completed of steps total, with the current as-of time.
- **RUN-22** Cancellation takes effect at the next step boundary. Results recorded up to that point are kept, and the run is marked `cancelled`.
- **RUN-23** Results are written atomically per run: a failed run's partial results are kept, but marked as partial.

### 11.4 Recorded provenance

- **RUN-30** Each run records:
  - the strategy `(spec_id, version)` and hash
  - the stress definitions `(stress_id, version)`
  - the full configuration and its hash
  - the set of `DataVersion`s read, and the underlying and data-source configuration versions
  - registry implementation versions used
  - software versions: the package, Python, DuckDB, Ibis, PyArrow, NumPy, SciPy, `exchange_calendars`
  - actor and channel (§15)
  - created, started and completed times
  - status and error

### 11.5 Flags

- **RUN-40** A run is flagged *data superseded* when any data version it read is replaced, deleted or purged (§6.7).

## 12. Results & Analytics

### 12.1 Position snapshots

- **RES-1** One position snapshot per security held or traded at each step, including the step at which it closes or settles. Fields:
  - identity: `run_id`, `step`, `as_of`, `structure_id`, `leg_id` (or `hedge`), `option_symbol`, `root`, `settlement_style`, `expiration`, `expiry_timestamp`, `strike`, `option_type`
  - position: signed `quantity`; time to expiry as `time_to_expiry_years`, `days_to_expiry` (fractional calendar days) and `trading_days_to_expiry`
  - prices: `mark`, `mark_source` (`mid`, `stale`, `fill`, `settlement`), `bid`, `ask`, `iv`, `index_level`, `forward`
  - values: `market_value`, `cash_flow`, `fees`, `period_pnl`, `cumulative_pnl`
  - per-contract vendor greeks: `delta`, `gamma`, `vega`, `theta`
  - dollar greeks (CONV-7): `dollar_delta`, `dollar_gamma_1pct`, `dollar_vega`, `dollar_theta`
  - `flags` (for example `stale_mark`, `vendor_flagged`, `missing_day_before`)
- **RES-2** The hedge's position snapshot has `dollar_delta = h · S` and zero for the other greeks.

### 12.2 Portfolio snapshots

- **RES-10** One portfolio snapshot per step:
  - sums of the position snapshots: market value, cash flow, fees, period P&L, dollar greeks
  - `cumulative_pnl`, `equity`, period return on capital
  - open structures, contracts held
  - worst stress loss across attached definitions
- **RES-11** Structure snapshots (totals per `structure_id` per step) are available as a view over the position snapshots.

### 12.3 Events

- **RES-20** Every event has a sequence number, step, as-of time, type, `structure_id` where relevant, a message, and structured details. Types include:
  - `entry`, `entry_skipped`
  - `trigger_fired` (with every condition that fired), `roll`, `close`
  - `settlement`, `forced_close_am`
  - `hedge_trade`
  - `stress_scaled`, `stress_skipped`, `stress_halted`, `stress_would_have_acted`, `stress_breach`
  - `selection_failed`, `stale_mark`, `order_not_filled`, `condition_null_greek`

### 12.4 Aggregate statistics

- **RES-30** Computed deterministically from the portfolio snapshots at the end of a run, and stored. **Annualization uses `periods_per_year`**, derived from the run's frequency (252 for `end_of_day`), never a hard-coded constant:
  - total P&L, total fees, cost drag (fees as a share of gross P&L)
  - annualized return on capital: mean period return × `periods_per_year`
  - annualized volatility: standard deviation of period returns × √`periods_per_year`
  - Sharpe ratio (risk-free rate configurable, default 0)
  - Sortino ratio (downside deviation of period returns)
  - maximum drawdown in dollars and as a percentage of peak equity, with peak, trough and recovery as-of times, and duration in trading days
  - Calmar ratio: annualized return over maximum drawdown percentage
  - best and worst period
  - percentage of positive periods
  - number of structures opened, percentage closed profitable, average P&L per structure
  - contracts traded, hedge notional traded
  - average and maximum absolute dollar delta, gamma, vega and theta
  - maximum stress loss and breach counts (STR-51)
  - a monthly P&L table
- **RES-31** Every statistic has a documented formula in the user documentation and in the API schema's descriptions (§14).

### 12.5 Export

- **RES-40** A run's position, portfolio and stress snapshots and its events can be exported as CSV or Parquet, and its summary and provenance as JSON.

## 13. Interfaces

### 13.1 Server & local security

- **INT-1** `optbt serve [--home DIR] [--port N] [--no-browser]` starts the API server and the GUI, binds to `127.0.0.1`, chooses a free port if none is given, and opens the browser.
- **INT-2** Local security follows the profiling tool:
  - loopback only
  - requests whose `Host` or `Origin` header is not the server's own are rejected
  - a random per-launch access token, carried in the opened URL and then kept in a cookie
- **INT-3** The server shuts down cleanly on Ctrl+C and closes storage.

### 13.2 HTTP API

- **INT-10** A REST/JSON API documented with OpenAPI covers every Phase 1 capability, grouped as:
  - data: imports, overlap, commit, versions, coverage, quality reports, delete, purge
  - reference: underlyings, data sources, calendar
  - specs: list, get, validate, publish, export, import
  - stress: list, get, validate, publish
  - registries: list, describe
  - runs: pre-flight, start, list, get, cancel, provenance
  - results: snapshots (paged), events, stress, statistics, export
  - jobs: list, get, cancel
  - audit: attempts
- **INT-11** Lists are paged with total counts. Large result sets are paged or streamed, never returned unbounded.
- **INT-12** The OpenAPI document is generated and kept current by a test. The front end's TypeScript types are generated from it.
- **INT-13** Non-finite floats are encoded as the strings `"Infinity"`, `"-Infinity"` and `"NaN"`.

### 13.3 Background jobs

- **INT-20** Ingest, commit, purge, runs, pre-flight on long ranges and exports run as jobs. Starting one returns a job immediately.
- **INT-21** A job has an id, kind, parameters, status (`queued` → `running` → `succeeded` | `failed` | `cancelled`), progress, timestamps, an error, and links to what it produced.
- **INT-22** **Jobs are persisted in the catalog** (not held only in memory), so job history survives a restart.
- **INT-23** Write jobs execute one at a time in submission order; reads stay responsive meanwhile (ARC-4).
- **INT-24** Queued jobs can be cancelled; running jobs are cancelled cooperatively at safe points (step boundaries for runs, batch boundaries for ingest).

### 13.4 GUI

- **INT-30** **Home:** the home directory location, counts of imports, specs and runs, recent runs with status, and running jobs.
- **INT-31** **Data:**
  - imports list
  - upload wizard: choose the file, watch ingest progress, review the quality report, review the overlap, choose the commit option
  - coverage heatmap by underlying with drill-down to a date's snapshot
  - delete and purge, with the affected runs listed before confirmation
- **INT-32** **Strategies:**
  - list
  - form editor generated from the spec schema, with registry pickers and parameter forms, unit pickers on time parameters, field-level validation from the dry run (SPEC-80), and a read-only *View as YAML*
  - version history, with any older version viewable and re-publishable as a new version
  - import and export
- **INT-33** **Stress definitions:** list, form editor, and version history, as for strategies.
- **INT-34** **New run:** choose the spec version, stress definitions and configuration (or a template); run the pre-flight check and show its findings; start.
- **INT-35** **Run page:**
  - header with status, provenance (§11.4) and flags
  - summary statistics
  - charts: equity curve, drawdown, dollar greeks over time, and worst stress loss over time
  - portfolio snapshot table
  - step drill-down: position snapshots, trades, hedge, stress by scenario and by structure, and events at that step
  - structures list, each with its legs, P&L and events
  - full events log with filters
  - export
- **INT-36** **Jobs panel:** always reachable; shows queued, running and recent jobs with progress, and notifies when a job finishes.
- **INT-37** Every chart has its data available as a table. The layout is desktop-first, minimum width 1280 px, for current Chrome, Edge, Firefox and Safari.

### 13.5 CLI

- **INT-40** The CLI (`click`) is a thin client of the service. Minimum commands:
  - `optbt serve`
  - `optbt data import <file> [--commit replace|add-new|ask]`, `optbt data list`, `optbt data coverage [--underlying]`, `optbt data quality <import_id>`, `optbt data delete --underlying --from --to`, `optbt data purge ...`
  - `optbt spec validate <file>`, `optbt spec publish <file>`, `optbt spec list`, `optbt spec show <id>[@version]`, `optbt spec export <id>[@version]`
  - `optbt stress validate|publish|list|show`
  - `optbt registry list [<type>]`, `optbt registry show <type> <name>`
  - `optbt run preflight ...`, `optbt run start --spec <id>@<v> [--stress <id>@<v> ...] --config <file>`, `optbt run list`, `optbt run show <run_id>`, `optbt run export <run_id> --format csv|parquet`, `optbt run cancel <run_id>`
  - `optbt demo` (§13.6)
- **INT-41** While the server is running, the CLI cannot open the same home directory (one DuckDB writer). Both report this clearly and name the remedy, as in the profiling tool.

### 13.6 Synthetic data & demo

- **INT-50** A **synthetic data generator** produces files in the exact ivolatility format (§6.1) for a synthetic index:
  - a seeded index path
  - listed expirations with both an AM-settled monthly root and a PM-settled weekly root
  - strike grids, implied vols from a simple skew model
  - Black-76 prices and greeks computed with the same time convention as the vendor (CONV-1, REF-5), bid-ask spreads from a spread model
  - expiration-day conventions (IV of −1 and zero greeks), and a configurable share of crossed quotes and flagged rows
- **INT-51** `optbt demo` creates a demo home: generated data imported and committed, the Appendix B specs published, the default stress definition, and one completed run of each spec.
- **INT-52** Vendor data is licensed and must never be committed to the repository. Tests depend only on synthetic data; optional local tests can run against real files supplied through an environment variable (§17).

## 14. Schemas & Documentation (AI-Readiness)

- **DOC-1** **One definition per configurable item.** Every spec element, registry implementation's parameters, stress definition, run configuration and result snapshot is a pydantic model with a description on every field. That single definition drives validation, the OpenAPI document, the GUI forms, the JSON Schemas returned by the registries (REG-3), and the generated reference documentation. Documentation is never written separately from the schema.
- **DOC-2** Descriptions state units, sign conventions, defaults and interactions (for example, that `cooldown_trading_days` does not delay a roll, or that `days` in a condition is measured in its `unit`). They are written so a reader with no other context, including a later AI agent, can configure the item correctly.
- **DOC-3** The conventions (§5.4) are published as a single document generated from the conventions module.
- **DOC-4** Public modules, classes and functions have docstrings in one style (Google or NumPy, chosen once). A README covers install, the demo, importing data, publishing a spec and running a backtest. A documentation site is later work (as FB-10 in the profiling tool).

## 15. Audit

- **AUD-1** Runs, imports, commits, deletes, purges and published definitions record the **actor** (the operating-system user in Phase 1) and the **channel** (`gui`, `api`, `cli` or `library`).
- **AUD-2** An **attempts log** records every requested operation with its outcome, including rejections: validation errors, pre-flight failures, and refused deletes. Attempts are never deleted.
- **AUD-3** Software versions are recorded on every run (RUN-30).
- **AUD-4** Content hashes are stored for every published definition (VER-2) and every import file (DATA-12). Tamper-evidence beyond hashes is later work.

## 16. Packaging & Environment

### 16.1 Stack

The stack follows the data profiling tool's current state.

| Layer | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Package metadata | `pyproject.toml` `[project]` table, the single source of dependencies; no `setup.py` |
| Layout | src layout: `src/options_backtester/` |
| Requirements files | `requirements.txt` = `-e .`; `build_requirements.txt` = `-e .[dev]` |
| Dependencies | DuckDB, Ibis (`ibis-framework[duckdb]`), PyArrow, NumPy, SciPy, pydantic, PyYAML, click, FastAPI, uvicorn, python-multipart, `exchange_calendars` |
| `dev` extra | pytest, pytest-cov, httpx, build, setuptools, wheel, Playwright |
| Build | `python -m build` to a wheel containing the built front end |
| Version | `0.1.0` initially; versioning from git tags follows the profiling tool's MB-2 approach once agreed there |
| Front end | React and TypeScript single-page app; Node.js only to develop or build it |
| Platform | Windows is the primary development platform; Linux and macOS should work |

**Suggested package layout:**

```
src/options_backtester/
  core/        domain models, conventions, time and snapshot types, schemas
  registry/    registry mechanism and the built-in implementations
  data/        DataManager: ingest, validation, versions, coverage
  reference/   underlyings, data sources, calendar, settlement sources
  storage/     StorageAdapter interface, DuckDB adapter, catalog and results access
  engine/      step loop, selectors, triggers, hedging, sizing, fills, accounting
  pricing/     Black-76, time-to-expiry calculation
  stress/      stress definitions, scenario types, evaluator, modes
  runs/        BacktestService, RunCoordinator, pre-flight, jobs
  results/     snapshot models, statistics, export
  licensing/   license-check hook (no-op in Phase 1; §16.2)
  server/      FastAPI app, local security, static serving
  cli/         click commands
  testdata/    synthetic data generator, demo
frontend/      React + TypeScript app
tests/
```

### 16.2 Distribution readiness

A protected, time-limited trial build is planned (project plan). Phase 1 does not build it, but must not prevent it:

- **DIST-1** **A license-check hook** runs when the service starts (for `serve`, the CLI and library use). In Phase 1 it always passes. A later build replaces it with a real check without changes elsewhere.
- **DIST-2** **The core is compilable.** The engine, pricing, stress, selectors, conditions and statistics (the intellectual property) must be compilable to native extension modules with Cython or Nuitka. In those packages: no reliance on reading source code at run time (`inspect.getsource` and similar), no generating code at run time, and no behavior that depends on `__file__` paths within the package.
- **DIST-3** **The compile boundary follows the architecture.** The pure engine library (ARC-2) sits behind interfaces the service calls. FastAPI routes and the pydantic models that FastAPI introspects stay plain Python, since compilation can interfere with annotation introspection.

## 17. Testing

- **TEST-1** **Golden engine tests** with small hand-checkable synthetic chains, each with expected results computed by hand. At least:
  - a long PM-settled call held to expiry and settled at intrinsic value
  - a short AM-settled call force-closed on its last trading day
  - a leg roll on a delta trigger
  - a structure roll on a time-to-expiry trigger, in calendar days and in trading days
  - an expiration chosen by each expiration selector, including `nth_expiration` across a weekend and a holiday
  - hedge-band behavior for Appendix B example 3 (no trade inside the band; reset to target outside it)
  - full hedging at every step for example 1
  - first-step cost under each fill model
  - notional sizing with whole and fractional rounding
  - a stale mark carried across a missing quote
  - each stress mode, including the exact Scale to limit size (STR-33) and a Halt run
- **TEST-2** **Invariant tests** (ENG-33) on many seeded synthetic runs.
- **TEST-3** **Determinism test:** two runs of the same inputs produce identical stored results.
- **TEST-4** **Point-in-time test:** any engine access past the step's as-of time raises an error (ARC-3).
- **TEST-5** **Time-convention tests:** time to expiry is computed to the minute from as-of and expiry timestamps (CONV-1), including AM-settled expiries at 09:30 and PM-settled expiries at 16:00. Black-76 at the computed time reproduces the synthetic generator's greeks exactly, and, in the optional real-data tests (TEST-10), the vendor's vega within a stated tolerance.
- **TEST-6** **Ingest tests** reproducing the quirks found in the real samples: IV of −1 and zero greeks on expiration day, `mean price` of 0 when the bid is 0, crossed quotes and zero asks, both roots sharing an expiration date, the `*` column, and MM/DD/YYYY dates.
- **TEST-7** **Adapter contract suite** (DATA-84).
- **TEST-8** **Validation tests** for every spec rule, including SPEC-52, SPEC-53 and explicit time units, and the YAML round trip (SPEC-81).
- **TEST-9** **API tests** against a real service with temporary directories, covering every endpoint; **front-end unit tests**; **end-to-end browser tests** (Playwright) of tasks T1 to T9.
- **TEST-10** **Optional real-data tests,** skipped unless an environment variable points at local vendor files, check ingest, the time convention and a sample run against real data without committing it.
- **TEST-11** **The Appendix B examples** each run end to end on synthetic data as acceptance tests.

## 18. Non-Functional Requirements & Documented Defaults

- **NFR-1** **Performance targets** (to be confirmed in the implementation plan):
  - ingest of one year of SPX data (about 750 MB of CSV) in under 5 minutes on a typical laptop
  - a single-structure spec over 10 years in under 60 seconds with data stored locally
  - the engine loads only the slice of each market snapshot its selectors can use (filtering by expiry window and needed columns), not the whole chain
- **NFR-2** **Responsiveness:** GUI pages show first content within 1 second; tables are paged or virtualized.
- **NFR-3** **Errors:** expected errors appear as readable messages in context; unexpected errors show a generic message, with details in the server log.
- **NFR-4** **No silent data loss:** data is deleted only by explicit delete or purge with confirmation; definitions and runs are never edited in place.
- **NFR-5** **Accessibility:** every function is reachable by keyboard, with visible focus, WCAG 2.1 AA contrast and labelled form fields.

**Documented defaults and simplifications** (to be revisited in later phases):

- Trades fill at the step at which the trigger is seen, which for end-of-day data is the close (CONV-6).
- Option marks are as of 16:15 ET and the index level as of 16:00 ET; the hedge trades at the 16:00 level (ENG-25).
- The hedge is a synthetic index position; financing, dividends and margin are not modeled.
- No interest on cash, no margin model; capital is a configured figure (portfolio margin is the assumed regime for later risk work).
- Stress revaluation is instantaneous, sticky strike, Black-76 with a configurable discount rate defaulting to 0.
- Time to expiry is calendar time over 365 days, to the minute, matching the vendor (REF-6).
- AM-settled contracts are always closed on their last trading day.
- The vendor `*` flag drives no behavior.
- The default fill model is `cross_spread`; the default commission is 0 and should be set by the user.

## 19. Out of Scope (Phase 1)

- AI and LLM features: the strategy-building chat, an agent choosing what to test, agent constructors (project plan, Phase 2 onward).
- Market-context calculations and conditions on them; forecasts; optimizers; the walk-forward construction loop.
- Stress scenario types other than underlying slides; limits other than maximum stress loss; drawdown-based risk budgets; greek and tenor budgets.
- P&L attribution by greek.
- Parameter sweeps and batch runs; run comparison views.
- An AM settlement-value table and holding AM-settled contracts to expiration.
- Hedging with futures or ETFs; financing and dividend modeling.
- Frequencies other than end of day; intraday data.
- Trading-time or event-weighted clocks (calendar time only).
- Equities, corporate actions, American exercise, underlyings without a cash-settled European index option chain.
- Multiple users, authentication, remote deployment, and databases other than DuckDB.
- The protected trial build, license enforcement and code compilation (§16.2 keeps them possible).
- A documentation site.

## 20. Open Items

| # | Item | Status |
| --- | --- | --- |
| 1 | Meaning of the vendor `*` flag | Being confirmed with ivolatility; stored, no behavior (DATA-13) |
| 2 | Vendor timing convention (16:15 ET snapshot; 16:00 and 09:30 ET expiries; calendar time over 365 days) | Inferred from the samples (REF-6); confirm with ivolatility |
| 3 | SPXW contracts on third Fridays | Expected in other files; no design impact |
| 4 | AM settlement values | Not supplied by the vendor; settlement-source plug-in point kept (REF-21) |
| 5 | Product, package and CLI names | Working names in ARC-7 (candidate: ProphetoVol) |
| 6 | Performance targets | To be confirmed in the implementation plan (NFR-1) |
| 7 | Default commission and fill model | Defaults in RUN-1; the user should set realistic values |

## 21. Milestones

Each milestone ends usable on its own, with a demo.

| Milestone | Delivers |
| --- | --- |
| **M1 Data foundation** | Package skeleton, `BacktestService`, `StorageAdapter` with the DuckDB adapter and contract suite, reference data (underlyings, data sources, calendar), ingest into market snapshots, validation and quality reports, overlap and commit, versions, delete and purge, coverage, synthetic data generator, data CLI commands, persisted jobs, audit log, license-check hook |
| **M2 Engine core** | Spec model and validation, registries with the Phase 1 implementations, time-to-expiry calculation, the step loop, selection, entries, triggers, rolls, expiration and settlement, hedging, sizing, fills, accounting and invariants, position and portfolio snapshots and events, run lifecycle and pre-flight, spec and run CLI commands, golden tests, Appendix B acceptance tests |
| **M3 Stress & analytics** | Stress definitions, the underlying slide, Black-76 revaluation, the three modes, stress snapshots, aggregate statistics, export |
| **M4 Server & GUI** | `optbt serve`, local security, the HTTP API and OpenAPI, the GUI (Home, Data, Strategies, Stress, New run, Run page, Jobs), `optbt demo`, end-to-end tests |

## Appendix A — ivolatility Column Mapping

| Vendor column | Normalized field | Type | Notes |
| --- | --- | --- | --- |
| `symbol` | `underlying` | string | One value per file (DATA-3) |
| `exchange` | `exchange` | string | Stored only |
| `date` | `as_of` | timestamp | The date at the data source's option snapshot time (16:15 ET); `as_of_date` is also stored |
| `adjusted close` | `index_level` | float | As of the index snapshot time (16:00 ET); the PM settlement value on expiration dates |
| `option symbol` | `option_symbol` | string | With `as_of`, the natural key; `root` parsed from it |
| `expiration` | `expiration` | date | MM/DD/YYYY |
| `strike` | `strike` | float | |
| `call/put` | `option_type` | `call` / `put` | From `C` / `P` |
| `style` | `exercise_style` | string | `E` required in Phase 1 |
| `ask` | `ask` | float | |
| `bid` | `bid` | float | |
| `mean price` | `vendor_mid` | float | Stored, not used for pricing |
| `iv` | `iv` | float, nullable | −1 stored as null |
| `volume` | `volume` | integer | |
| `open interest` | `open_interest` | integer | |
| `stock price for iv` | `forward` | float, nullable | The vendor's per-series forward; ignored on expiration day |
| `*` | `vendor_flag` | boolean | Meaning unconfirmed |
| `delta` | `delta` | float, nullable | Null on expiration day |
| `vega` | `vega` | float, nullable | Per one vol point; null on expiration day |
| `gamma` | `gamma` | float, nullable | Null on expiration day |
| `theta` | `theta` | float, nullable | Per calendar day; null on expiration day |
| `rho` | `rho` | float, nullable | Null on expiration day |
| (derived) | `index_as_of` | timestamp | The date at the index snapshot time (16:00 ET) |
| (derived) | `root` | string | `SPX`, `SPXW` |
| (derived) | `settlement_style` | `AM` / `PM` | From the underlying's root configuration |
| (derived) | `expiry_timestamp` | timestamp | Expiration date at the root's expiry time (CONV-3) |
| (derived) | `import_id` | string | The import that supplied the data |

## Appendix B — Example Strategies

These ship as sample specs and acceptance tests (SPEC-82, TEST-11). Where the original description left a choice open, the choice made here is noted.

**Example 1 — Delta-hedged short call.** Short a 30-delta, 45-day call; hedge delta to flat at every step; roll if the call's delta goes above 50 or below 15, or it has 15 days or fewer left.

```yaml
id: short_call_hedged
description: Short 30-delta 45-day SPX call, delta hedged at every step, rolled on delta or time.
underlying: SPX
legs:
  - id: short_call
    option_type: call
    side: short
    ratio: 1
    expiration: {selector: target_days, days: 45}
    strike: {selector: delta, target: 0.30}
entry: {schedule: when_flat}
triggers:
  - name: roll_on_delta_or_time
    scope: {leg: short_call}
    action: roll
    any_of:
      - {condition: leg_abs_delta_above, leg: short_call, threshold: 0.50}
      - {condition: leg_abs_delta_below, leg: short_call, threshold: 0.15}
      - {condition: leg_days_to_expiry_at_or_below, leg: short_call, days: 15, unit: calendar_days}
expiry_handling: close_structure
hedge: {rule: band, scope: structure, lower: 0.0, upper: 0.0, target: 0.0}
sizing: {method: contracts, quantity: 10}
```

**Example 2 — Long butterfly, unhedged.** Buy a 60-day butterfly: short at-the-money call and put at the same strike, long 25-delta call and put wings; roll at 25 days or fewer. *Choice made:* put and call wings (an iron butterfly); the short put uses the short call's strike so both shorts share one strike.

```yaml
id: long_butterfly_60d
description: 60-day SPX iron butterfly, short ATM straddle, long 25-delta wings, rolled at 25 days to expiry.
underlying: SPX
legs:
  - id: short_call
    option_type: call
    side: short
    ratio: 1
    expiration: {selector: target_days, days: 60}
    strike: {selector: atm}
  - id: short_put
    option_type: put
    side: short
    ratio: 1
    expiration: {selector: same_as_leg, leg: short_call}
    strike: {selector: same_strike_as, leg: short_call}
  - id: long_call
    option_type: call
    side: long
    ratio: 1
    expiration: {selector: same_as_leg, leg: short_call}
    strike: {selector: delta, target: 0.25}
  - id: long_put
    option_type: put
    side: long
    ratio: 1
    expiration: {selector: same_as_leg, leg: short_call}
    strike: {selector: delta, target: 0.25}
entry: {schedule: when_flat}
triggers:
  - name: roll_at_25_days
    scope: structure
    action: roll
    any_of:
      - {condition: structure_min_days_to_expiry_at_or_below, days: 25, unit: calendar_days}
expiry_handling: close_structure
hedge: {rule: none}
sizing: {method: contracts, quantity: 10}
```

**Example 3 — Put diagonal with a hedge band.** Short a 45-day 25-delta put, long a 75-day 20-delta put; keep net delta between 0 and +0.08 per spread, resetting to +0.03 when outside. *Choice made:* the original description gave no roll rule, so the whole spread is re-established when the short put reaches 15 days, the general default for backtests.

```yaml
id: put_diagonal_banded
description: Short 45-day 25-delta SPX put, long 75-day 20-delta put, hedged within a 0 to +0.08 delta band.
underlying: SPX
legs:
  - id: short_put
    option_type: put
    side: short
    ratio: 1
    expiration: {selector: target_days, days: 45}
    strike: {selector: delta, target: 0.25}
  - id: long_put
    option_type: put
    side: long
    ratio: 1
    expiration: {selector: target_days, days: 75}
    strike: {selector: delta, target: 0.20}
entry: {schedule: when_flat}
triggers:
  - name: reestablish_at_15_days
    scope: structure
    action: roll
    any_of:
      - {condition: leg_days_to_expiry_at_or_below, leg: short_put, days: 15, unit: calendar_days}
expiry_handling: close_structure
hedge: {rule: band, scope: structure, lower: 0.0, upper: 0.08, target: 0.03}
sizing: {method: contracts, quantity: 10}
```

**Example of a dailies selection** (not an acceptance test; shows the unit-explicit selectors):

```yaml
# leg fragment: the next trading day's PM-settled expiration, 50-delta call
expiration: {selector: trading_days_out, n: 1, filter: {settlement_styles: [PM]}}
strike: {selector: atm}
```

**Example stress definition and run configuration:**

```yaml
# stress definition
id: default_slide
description: Underlying slide from -20% to +20% in 5% steps; reported, no limit.
scenarios:
  - id: slide
    type: underlying_slide
    moves_pct: [-20, -15, -10, -5, 5, 10, 15, 20]
```

```yaml
# run configuration
underlying: SPX
data_source: ivolatility_eod
frequency: end_of_day
start_date: 2024-04-11
end_date: 2024-06-24
capital: 1000000
fill_model: cross_spread
commission_per_contract: 0.0
hedge_cost_bps: 0.0
rounding: whole
stress_mode: monitor
```

## Appendix C — Glossary

| Term | Meaning |
| --- | --- |
| Step | One point in a run, with an as-of timestamp. In Phase 1, one end-of-day close per trading day. |
| As-of | The timestamp a snapshot describes. |
| Snapshot | The complete state of something as of a step: market, position, portfolio or stress. |
| Frequency | How often a run steps. Phase 1: `end_of_day`. |
| Time to expiry | The model input: years from the as-of timestamp to the expiry timestamp, calendar time over 365 days. |
| Days to expiry | Time to expiry in fractional calendar days, for people. |
| Trading days to expiry | Trading days after the as-of date up to and including the expiration date. |
| AM-settled | Settles on a special opening value on expiration day, at 09:30 ET; for SPX, the `SPX` root monthlies. Last trading day is the day before expiration. |
| PM-settled | Settles on the index close at 16:00 ET on expiration day; for SPX, the `SPXW` root. |
| SET | The AM settlement value of the S&P 500 index. Not available in Phase 1. |
| Forward | The vendor's per-series forward (`stock price for iv`). |
| Structure | One instance of a strategy's legs, opened together and managed together. |
| Unit | One structure with each leg at its ratio. |
| Sticky strike | Each contract keeps its own implied vol when the index moves. |
| Black-76 | The option pricing formula on a forward price, used for stress revaluation. |
| Constructor | The component that turns a step's state into orders. Phase 1: the rules-based constructor. |
| Registry | A named set of interchangeable implementations of one component type. |

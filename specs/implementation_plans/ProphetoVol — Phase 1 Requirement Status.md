# ProphetoVol — Phase 1 Requirement Status

Oct 27, 2026 · @Chuck · **Up to date through plan Phase 11 (selection and entries).** · Tracks: *ProphetoVol — Phase 1 Requirements Specification* (v7, agreed) against *ProphetoVol — Phase 1 Implementation Plan* (v5, agreed).

One row per requirement ID. This file is updated in every portion of work, in the same change as the code, so each commit carries its own status changes.

- **Done:** nothing is left to build for this requirement.
- **Partial:** some of it is built; *Remaining or notes* says what is left and in which plan phase.
- **Not started:** *Remaining or notes* gives the plan phase that builds it.
- **Done in** names plan phases (the build steps of the implementation plan, not the product phases of the roadmap). Each plan phase is one commit, tagged by the project owner. Phase 0 is the feasibility check.
- Cross-cutting rules (for example DOC-1, AUD-2, TIME-3) stay **Partial** while new code keeps arriving: they are enforced on everything built so far and apply to each new piece.
- *Tests* are paths under `tests/`.

## Summary

**222 requirements:** 69 done, 63 partial, 90 not started.

| Milestone | Plan phases | Status |
| --- | --- | --- |
| **M1 Data foundation** | 1–8 | **Done:** phases 1–8; checkpoint 1 held Oct 26, 2026 |
| **M2 Engine core** | 9–15 | **In progress:** phases 9–11 done (Oct 27, 2026); 12–15 to go |
| **M3 Stress and analytics** | 16–18 | Not started |
| **M4 Server and GUI** | 19–24 | Not started |

| Plan phase | Content | Completed |
| --- | --- | --- |
| 0 | Feasibility check | Oct 25, 2026 |
| 1 | Repository foundation | Oct 25, 2026 |
| 2 | Conventions, time, calendar and registries | Oct 25, 2026 |
| 3 | Storage adapter and catalog | Oct 25, 2026 |
| 4 | Jobs and audit | Oct 25, 2026 |
| 5 | Synthetic data generator | Oct 25, 2026 |
| 6 | Ingest, normalization, validation and quality reports | Oct 26, 2026 |
| 7 | Overlap, commit, versions, delete, purge, invalidation and coverage | Oct 25, 2026 |
| 8 | Data CLI, documentation and checkpoint 1 | Oct 26, 2026 |
| 9 | Spec model, validation and publishing | Oct 27, 2026 |
| 10 | Run configuration, pre-flight and market data access | Oct 27, 2026 |
| 11 | Selection and entries | Oct 27, 2026 |
| 12 | Book, marking, fills, sizing, hedging and accounting | — |
| 13 | Triggers, rolls, expiry, settlement and the step loop | — |
| 14 | Run lifecycle, results storage and the run CLI | — |
| 15 | Acceptance, determinism, run time and checkpoint 2 | — |
| 16–24 | M3–M4 (see the implementation plan, §8–§9) | — |

| Area | Done | Partial | Not started |
| --- | --- | --- | --- |
| Architecture (§4) | 2 | 3 | 2 |
| Time, steps and snapshots (§5.1) | 0 | 3 | 0 |
| Versioning (§5.3) | 1 | 3 | 0 |
| Conventions (§5.4) | 0 | 10 | 0 |
| Registries (§5.5) | 1 | 2 | 1 |
| Data module (§6) | 22 | 8 | 0 |
| Reference data (§7) | 7 | 1 | 0 |
| Strategy specification (§8) | 26 | 5 | 19 |
| Engine (§9) | 0 | 1 | 18 |
| Stress module (§10) | 0 | 1 | 17 |
| Runs (§11) | 1 | 7 | 3 |
| Results and analytics (§12) | 0 | 0 | 8 |
| Interfaces (§13) | 4 | 6 | 15 |
| Schemas and documentation (§14) | 1 | 3 | 0 |
| Audit (§15) | 1 | 3 | 0 |
| Distribution (§16.2) | 0 | 1 | 0 |
| Testing (§17) | 3 | 3 | 5 |
| Non-functional (§18) | 0 | 3 | 2 |

## Architecture (§4)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| ARC-1 | BacktestService is the only component that opens storage; clients are thin | **Partial** | Phase 3, 8 (CLI commands as thin service clients) | API (19-20) built as a thin client | `unit/test_service.py`, `unit/test_data_cli.py` |
| ARC-2 | The engine is a pure library with no I/O | Not started |  | Phase 9-13 |  |
| ARC-3 | Point-in-time access through MarketDataView, enforced in code | **Partial** | Phase 10 (MarketDataView refuses any later as-of time; the provider stays service-side) | the engine reads only views (13) | `unit/test_market_data.py` |
| ARC-4 | One writer: service owns read-write connections; write jobs one at a time; readers on cursors | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py` (readers), `unit/test_jobs.py` |
| ARC-5 | Extensible component types are registries of named implementations | **Partial** | Phase 2, 9 (the M2 registries) | stress registries (16) | `unit/test_registry.py`, `unit/test_strategy.py` |
| ARC-6 | Single-user, local server bound to 127.0.0.1 | Not started |  | Phase 19 |  |
| ARC-7 | Names: ProphetoVol; package and CLI `prophetovol`; home `~/.prophetovol` | **Done** | Phase 1 |  | `unit/test_package.py`, `packaging/test_wheel.py`, `unit/test_core.py` |

## Time, steps and snapshots (§5.1)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| TIME-1 | A run advances in steps with as-of timestamps; frequency is configuration | **Partial** | Phase 10 (steps with sequence numbers and as-of instants; frequency in the run configuration) | the step loop (13) | `unit/test_run_preflight.py` |
| TIME-2 | Four snapshot kinds: market, position, portfolio, stress | **Partial** | Phase 6 (market snapshots) | position and portfolio (12), stress (16) snapshots | `unit/test_ingest.py` |
| TIME-3 | Time quantities are named by their units | **Partial** | Phase 2, 3 | applies to every later field; checked in each phase | `unit/test_time.py` |

## Versioning (§5.3)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| VER-1 | Published definitions are immutable; every change is a new integer version | **Partial** | Phase 3, 4, 9 (strategy specs) | stress definitions (16) | `contract/test_adapter_contract.py`, `unit/test_audit.py`, `unit/test_strategy.py` |
| VER-2 | Each published version stores a content hash of its canonical JSON | **Partial** | Phase 3, 9 (specs, hashed in canonical form) | stress definitions (16) | `contract/test_adapter_contract.py`, `unit/test_strategy.py` |
| VER-3 | A run records by reference everything it used | **Partial** | Phase 10 (resolved configuration hashed; spec version and hash and the data versions to read fixed by pre-flight) | recorded on the run (14) | `unit/test_run_preflight.py` |
| VER-4 | Market snapshots are versioned per (underlying, as_of) | **Done** | Phase 3, 7 |  | `contract/test_adapter_contract.py`, `contract/test_lifecycle_contract.py` |

## Conventions (§5.4)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| CONV-1 | Time to expiry: calendar minutes on the exchange clock over 365 days | **Partial** | Phase 2, internal conventions change (stated as ProphetoVol's own; IV rescaling rule in DATA-15) | stored per row at ingest from 6; used by engine and stress (12-17) | `unit/test_time.py` |
| CONV-2 | Trading days to expiry: after the as-of date through the settlement date | **Partial** | Phase 2 | stored at ingest from 6; used by selectors and triggers (11, 13) | `unit/test_time.py` |
| CONV-3 | Settlement date, expiry and last trading day (incl. Saturday-dated) | **Partial** | Phase 2 | stored at ingest from 6; forced closes (13) | `unit/test_time.py` |
| CONV-4 | Delta targets are absolute values | **Partial** | Phase 2 (published text) | delta selectors (11) | `unit/test_conventions.py` |
| CONV-5 | At the money means 50 delta of the leg's own type | **Partial** | Phase 2 (published text) | `atm` selector (11) | `unit/test_conventions.py` |
| CONV-6 | Trades execute at the step where the trigger is observed | **Partial** | Phase 2 (published text) | engine (12-13) | `unit/test_conventions.py` |
| CONV-7 | Dollar greek formulas | **Partial** | Phase 2 (formulas), internal conventions change (units from CONV-10) | position snapshots (12) | `unit/test_conventions.py` |
| CONV-8 | Signs: positive quantity is long; positive cash flow is received | **Partial** | Phase 2 (published text) | accounting (12) | `unit/test_conventions.py` |
| CONV-9 | A roll re-establishes the structure by default | **Partial** | Phase 2 (published text) | rolls (13) | `unit/test_conventions.py` |
| CONV-10 | Internal price, IV and greek conventions (undiscounted forward delta, vega per point, theta per day) | **Partial** | Phase 5 (Black-76 in these conventions), internal conventions change (stated; vendor parameter removed) | snapshots produced in them by ingest from 6; used by selection, hedging and stress (11-17) | `unit/test_black76.py`, `unit/test_conventions.py` |

## Registries (§5.5)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| REG-1 | The Phase 1 registries and their implementations | **Partial** | Phase 2 (settlement_source), 9 (selectors, schedules, conditions, actions, hedge, sizing, fills and constructor registered with their parameter models), 11 (selectors and schedules behave) | conditions, actions, hedge, sizing, fills, constructor behavior (12-13); stress types and modes (16-17) | `unit/test_registry.py`, `unit/test_strategy.py`, `unit/test_selection.py`, `unit/test_entries.py` |
| REG-2 | Every implementation declares name, description, documented parameter model, version | **Done** | Phase 2 | enforced at registration for every future implementation | `unit/test_registry.py` |
| REG-3 | Registries are discoverable with descriptions and JSON Schemas | **Partial** | Phase 2 (service level), 8 (CLI `registry list/show`) | API (20) | `unit/test_registry.py`, `unit/test_data_cli.py` |
| REG-4 | Condition types are pluggable | Not started |  | Phase 13 |  |

## Data module (§6)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DATA-1 | Input is the 22-column ivolatility CSV | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-2 | Date format, `*` flag, and both option symbol formats | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-3 | One underlying per import, from one or more files | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-4 | Imports accept several CSVs, folders or zips; size limit | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-10 | Uploads are streamed; ingest runs as a job with progress | **Partial** | Phase 6 (local files and zips, hashed in chunks; ingest as a job with progress) | HTTP upload streamed to the server (20) | `unit/test_ingest.py` |
| DATA-11 | Ingest validates and normalizes into staged Parquet under a new import id | **Done** | Phase 3 (staged storage), 6 (ingest) |  | `unit/test_ingest.py`, `contract/test_adapter_contract.py` |
| DATA-12 | Each file's SHA-256 is recorded; duplicate files are reported | **Done** | Phase 3 (storage and lookup), 6 (hashing and the file_already_imported finding) | cancelling is the commit choice (DATA-31, 7) | `unit/test_ingest.py` |
| DATA-13 | Normalization rules and derived columns computed at ingest | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-14 | The forward: vendor per-series from 2018-06-25, parity fit before | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| DATA-15 | Data-source adapters convert into internal conventions; originals kept in `vendor_*` | **Done** | Phase 6 (the ivolatility adapter) | IV rescaling is not exercised: the only configured time convention equals CONV-1 | `unit/test_ingest.py` |
| DATA-20 | Validation checks and the quality report | **Done** | Phase 6, checkpoint 1 corrections (low-count ratio configurable on the data source) |  | `unit/test_ingest.py` |
| DATA-21 | Quality report viewable in GUI and CLI, kept permanently | **Partial** | Phase 6 (stored permanently; `quality_report` in the service), 8 (CLI `data quality`) | GUI (21) | `unit/test_ingest.py`, `unit/test_data_cli.py` |
| DATA-30 | Overlap with active data shown before commit | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-31 | Commit choices: replace, add new dates only, cancel | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-32 | Commit is atomic | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-33 | Committing or replacing data queues invalidation | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-40 | At most one active version per (underlying, as_of); superseded kept until purge | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-41 | Version registry in the catalog, contents in Parquet; identity (underlying, as_of, import_id) | **Done** | Phase 3 |  | `contract/test_adapter_contract.py` |
| DATA-50 | Delete by underlying and range deactivates versions | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-51 | Purge removes superseded or deleted data and reclaims space | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-52 | Affected runs listed and confirmed before delete or purge | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-53 | Delete and purge recorded in the audit trail | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-60 | Runs that read changed data are flagged data superseded | **Done** | Phase 7 |  | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| DATA-61 | The data-superseded flag is visible on runs and in the API | **Partial** | Phase 7 (persisted flags and service read) | Run lists/pages (14, 23) and API (20) | `unit/test_data_lifecycle.py` |
| DATA-70 | Coverage view per trading day | **Partial** | Phase 7 (daily coverage and monthly summaries in service), 8 (CLI `data coverage`) | GUI (21) | `unit/test_data_lifecycle.py`, `unit/test_data_cli.py` |
| DATA-80 | Parquet layout per underlying/year/month, one file per import; active-version filtering | **Done** | Phase 3, 7 |  | `unit/test_duckdb_storage.py`, `contract/test_lifecycle_contract.py` |
| DATA-81 | Reads go through Ibis | **Partial** | Phase 3, 7 (catalog and active market reads), 10 (chunked market reads for runs) | result reads (14) | `contract/test_lifecycle_contract.py`, `contract/test_market_read_contract.py` |
| DATA-82 | Writes go through the StorageAdapter interface | **Partial** | Phase 3, 7 (commit, delete, purge, active snapshots) | Run result writes (14) | `contract/test_lifecycle_contract.py` |
| DATA-83 | Physical layout is known only to the adapter | **Partial** | Phase 3, 7 (all lifecycle file operations inside adapter), 10 (the provider reads through adapter operations only) | results (14) | `contract/test_lifecycle_contract.py` |
| DATA-84 | Adapter contract test suite | **Partial** | Phase 3, 7, 10 (exact-version chunk reads, horizon filter, index levels, purged versions) | Atomic run writes (14) | `contract/test_adapter_contract.py`, `contract/test_lifecycle_contract.py`, `contract/test_market_read_contract.py` |

## Reference data (§7)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| REF-1 | Underlying configuration with expiry times and all vendor roots | **Done** | Phase 2, 3 (seeded) |  | `unit/test_reference.py`, `unit/test_service.py` |
| REF-2 | Underlying configurations are editable as versioned definitions | **Done** | Phase 3, 4 |  | `unit/test_service.py`, `unit/test_audit.py` |
| REF-5 | Data source configuration and timing | **Done** | Phase 2, 3 (seeded), internal conventions change (`internal_greeks_from`), checkpoint 1 corrections (`low_contract_ratio`) |  | `unit/test_reference.py` |
| REF-6 | Timing confirmed on real data; held in configuration | **Done** | Phase 0 (confirmed), 2 (configuration) |  | `unit/test_reference.py` |
| REF-10 | NYSE trading calendar from exchange_calendars | **Done** | Phase 2 |  | `unit/test_calendar.py` |
| REF-11 | The calendar version is recorded on runs | **Partial** | Phase 2 (version available) | recorded on runs (14) | `unit/test_calendar.py` |
| REF-20 | Settlement-source registry with pm_index_close | **Done** | Phase 2 |  | `unit/test_registry.py` |
| REF-21 | No AM settlement source; AM contracts never held to expiry | **Done** | Phase 2 | the forced close itself is SPEC-51 (13) | `unit/test_registry.py` |

## Strategy specification (§8)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| SPEC-1 | StrategySpec contents | **Done** | Phase 9 |  | `unit/test_strategy.py` |
| SPEC-2 | Leg fields | **Done** | Phase 9 |  | `unit/test_strategy.py` |
| SPEC-3 | Leg references without cycles, resolved in dependency order | **Done** | Phase 9 (references checked, cycles named, selection order computed), 11 (legs selected in that order) |  | `unit/test_strategy.py`, `unit/test_selection.py` |
| SPEC-4 | Selection is atomic across legs | **Partial** | Phase 11 (all legs or none; the failure names the leg, its selector and why) | recorded as a selection_failed event (13) | `unit/test_selection.py` |
| SPEC-10 | `target_days` expiration selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-11 | `trading_days_out` expiration selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-12 | `nth_expiration` expiration selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-13 | `same_as_leg` and `next_after_leg` selectors | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-14 | Expiration filters | **Done** | Phase 11 (standard_monthly_only by date, plan §7.5 answer 5) |  | `unit/test_selection.py` |
| SPEC-15 | Expirations never eligible at/after expiry; AM never on/after last trading day | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-20 | `delta` strike selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-21 | `atm` strike selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-22 | `forward` strike selector | **Done** | Phase 11 (default tolerance: the usual spacing around the target, plan §7.5 answer 6) |  | `unit/test_selection.py` |
| SPEC-23 | `same_strike_as` strike selector | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-24 | `strike_offset` strike selector | **Done** | Phase 11 (default tolerance: the usual spacing around the target, plan §7.5 answer 6) |  | `unit/test_selection.py` |
| SPEC-25 | No-match handling | **Partial** | Phase 11 (skip_entry; nearest_any with a warning) | the warning recorded as an event (13) | `unit/test_selection.py` |
| SPEC-26 | Selection uses only eligible contracts | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-27 | Delta selection uses vendor delta; null delta not eligible | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-28 | Quote filters | **Done** | Phase 11 |  | `unit/test_selection.py` |
| SPEC-30 | `once` entry schedule | **Done** | Phase 11 |  | `unit/test_entries.py` |
| SPEC-31 | `when_flat` entry schedule with cooldown | **Done** | Phase 11 |  | `unit/test_entries.py` |
| SPEC-32 | `every_n_trading_days` entry schedule | **Done** | Phase 11 |  | `unit/test_entries.py` |
| SPEC-33 | `weekdays` entry schedule | **Done** | Phase 11 |  | `unit/test_entries.py` |
| SPEC-34 | `max_open` for schedules | **Done** | Phase 11 |  | `unit/test_entries.py` |
| SPEC-35 | Failed entries retried at the next scheduled step | **Partial** | Phase 11 (schedules are simply due again; nothing is queued) | applied by the step loop (13) | `unit/test_entries.py` |
| SPEC-40 | Trigger structure | **Done** | Phase 9 (trigger model: name, scope, action, any_of) |  | `unit/test_strategy.py` |
| SPEC-41 | Phase 1 trigger conditions | Not started |  | Phase 13 |  |
| SPEC-42 | Condition evaluation; null greeks evaluate false | Not started |  | Phase 13 |  |
| SPEC-43 | Close and roll actions | Not started |  | Phase 13 |  |
| SPEC-44 | One action per structure per step, with precedence | Not started |  | Phase 13 |  |
| SPEC-45 | Roll whose opening side fails selection | Not started |  | Phase 13 |  |
| SPEC-46 | Structure P&L per unit | Not started |  | Phase 13 |  |
| SPEC-50 | PM-settled legs settle at intrinsic value | Not started |  | Phase 13 (pm_index_close ready from 2) |  |
| SPEC-51 | AM-settled legs force-closed on their last trading day | Not started |  | Phase 13 |  |
| SPEC-52 | Validation rejects holding AM-settled legs to expiration | **Done** | Phase 9 |  | `unit/test_strategy.py` |
| SPEC-53 | Validation warns when the engine will force-close an AM leg | **Done** | Phase 9 (covering trigger: a days-to-expiry condition with days >= 1, plan §7.5) |  | `unit/test_strategy.py` |
| SPEC-54 | `expiry_handling` options | Not started |  | Phase 13 |  |
| SPEC-55 | PM legs closed early when the settlement date is a missing day | Not started |  | Phase 13 |  |
| SPEC-60 | `none` hedge rule | Not started |  | Phase 12 |  |
| SPEC-61 | `band` hedge rule | Not started |  | Phase 12 |  |
| SPEC-62 | Hedge instrument: fractional synthetic index position | Not started |  | Phase 12 |  |
| SPEC-63 | Hedging evaluated after option trades | Not started |  | Phase 12 |  |
| SPEC-64 | Hedge closed with its structure | Not started |  | Phase 12 |  |
| SPEC-70 | `contracts` sizing | Not started |  | Phase 12 |  |
| SPEC-71 | `notional` sizing | Not started |  | Phase 12 |  |
| SPEC-72 | Rounding of structure units | Not started |  | Phase 12 |  |
| SPEC-73 | Re-sizing on rolls | Not started |  | Phase 12 |  |
| SPEC-80 | Dry-run validation with field paths | **Done** | Phase 9 |  | `unit/test_strategy.py`, `unit/test_spec_cli.py` |
| SPEC-81 | Authoring and exact YAML round trip | **Partial** | Phase 9 (YAML and JSON import through the CLI and the service; exact round-trip export) | API (20), GUI editor (22) | `unit/test_strategy.py`, `unit/test_spec_cli.py` |
| SPEC-82 | Appendix B examples ship as sample specs | **Partial** | Phase 9 (shipped as package data, validated; `spec examples`) | acceptance tests (15) | `unit/test_strategy.py` |

## Engine (§9)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| ENG-1 | The step loop and its nine steps in order | Not started |  | Phase 13 |  |
| ENG-2 | The constructor interface; `rules` constructor | Not started |  | Phase 13 |  |
| ENG-3 | Several structures of one spec tracked separately | Not started |  | Phase 13 |  |
| ENG-4 | Time-dependent calculations from timestamps and calendar, never step counts | **Partial** | Phase 11 (entry schedules and trading days counted on the calendar; selection from stored times to expiry) | trading days held and the step loop (13) | `unit/test_entries.py` |
| ENG-10 | Determinism | Not started |  | Phase 12-15 |  |
| ENG-20 | Valid quotes and the mid | Not started |  | Phase 12 |  |
| ENG-21 | Marking, stale marks and warnings | Not started |  | Phase 12 |  |
| ENG-22 | Final marks of settled and force-closed legs | Not started |  | Phase 12 |  |
| ENG-23 | The series forward used for the forward selector and stress | Not started |  | Phase 11, 16 (column from 6) |  |
| ENG-24 | Greeks are the vendor's | Not started |  | Phase 12 (the snapshot's internal greeks, DATA-15) |  |
| ENG-25 | Two times in one snapshot (16:15 options, 16:00 index) | Not started |  | Phase 12 |  |
| ENG-30 | Accounting: market value, cash flows, period P&L | Not started |  | Phase 12 |  |
| ENG-31 | Fees reported separately | Not started |  | Phase 12 |  |
| ENG-32 | Equity = capital + cumulative P&L | Not started |  | Phase 12 |  |
| ENG-33 | Accounting invariants checked every run | Not started |  | Phase 12 |  |
| ENG-40 | Fill models | Not started |  | Phase 12 |  |
| ENG-41 | Orders with invalid quotes; retries; forced-close exception | Not started |  | Phase 12-13 |  |
| ENG-42 | Commission and hedge cost | Not started |  | Phase 12 |  |
| ENG-43 | Opening at worse than mid shows a first-step loss | Not started |  | Phase 12 |  |

## Stress module (§10)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| STR-1 | StressDefinition with scenarios and an optional loss limit | Not started |  | Phase 16 |  |
| STR-2 | Runs attach zero or more stress definitions | Not started |  | Phase 16 |  |
| STR-10 | `underlying_slide` scenario type and `default_slide` | Not started |  | Phase 16 |  |
| STR-11 | Scenario-type registry as the extension point | Not started |  | Phase 16 |  |
| STR-20 | Black-76 revaluation on the series forward | **Partial** | Phase 5 (Black-76 prices and greeks in the internal conventions) | stress revaluation on the series forward (16) | `unit/test_black76.py` |
| STR-21 | Shocked forward, unchanged vol (sticky strike) | Not started |  | Phase 16 |  |
| STR-22 | Stress P&L from model values only | Not started |  | Phase 16 |  |
| STR-23 | Null IV revalued at intrinsic and flagged | Not started |  | Phase 16 |  |
| STR-30 | Enforcement modes: Monitor, Scale to limit, Halt run | Not started |  | Phase 17 |  |
| STR-31 | Only opening orders are gated | Not started |  | Phase 17 |  |
| STR-32 | The checked book includes the required hedge | Not started |  | Phase 17 |  |
| STR-33 | Exact Scale-to-limit size | Not started |  | Phase 17 |  |
| STR-34 | Breaches with no trade are reported | Not started |  | Phase 17 |  |
| STR-35 | Every attached limit must pass | Not started |  | Phase 17 |  |
| STR-40 | Modes documented in the configuration schema | Not started |  | Phase 17 |  |
| STR-50 | Stress snapshots per step | Not started |  | Phase 16 |  |
| STR-51 | Run-level stress statistics | Not started |  | Phase 16 |  |
| STR-52 | Stress P&L per structure | Not started |  | Phase 16 |  |

## Runs (§11)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| RUN-1 | Run definition and configuration fields | **Done** | Phase 10 |  | `unit/test_run_preflight.py` |
| RUN-2 | Configuration templates; full resolved configuration and hash stored | **Partial** | Phase 10 (named, versioned templates saved and listed through the service; resolved configuration and its hash) | the run stores them (14); CLI (14), GUI (23) | `unit/test_run_preflight.py` |
| RUN-10 | Pre-flight checks | **Partial** | Phase 10 (spec, configuration, every trading day's active snapshot, non-empty chains, engine columns) | stress definitions validate (16) | `unit/test_run_preflight.py` |
| RUN-11 | Pre-flight reports all problems; missing days; fixes the step schedule | **Partial** | Phase 10 (every problem at once; missing days block or are skipped with SPEC-55 warnings; the step schedule) | missing_day_before flag on the next step's position snapshots (12) | `unit/test_run_preflight.py` |
| RUN-12 | Pre-flight available on its own | **Partial** | Phase 10 (readiness check in the service, audited as run.preflight) | CLI `run preflight` (14), API (20) | `unit/test_run_preflight.py` |
| RUN-20 | Run statuses; runs left queued or running marked failed (interrupted) | **Partial** | Phase 4 (recovery pattern for jobs) | run statuses and recovery of interrupted runs (14) | `unit/test_jobs.py` |
| RUN-21 | Run progress: steps done of total, with current as-of | Not started |  | Phase 14 (job progress ready from 4) |  |
| RUN-22 | Cancellation at the next step boundary keeps results | Not started |  | Phase 14 (cooperative cancellation ready from 4) |  |
| RUN-23 | Results written in one transaction when the run ends | Not started |  | Phase 14 |  |
| RUN-30 | Recorded provenance of a run | **Partial** | Phase 1 (software versions collector) | provenance recorded on runs (14) | `unit/test_core.py` |
| RUN-40 | Runs flagged data superseded | **Partial** | Phase 7 (invalidation against seeded run provenance) | Record each real run's read versions (14) | `unit/test_data_lifecycle.py` |

## Results and analytics (§12)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| RES-1 | Position snapshot fields | Not started |  | Phase 12 |  |
| RES-2 | Hedge position snapshot greeks | Not started |  | Phase 12 |  |
| RES-10 | Portfolio snapshot fields | Not started |  | Phase 12 |  |
| RES-11 | Structure snapshots as a view | Not started |  | Phase 14 |  |
| RES-20 | Events and their types | Not started |  | Phase 12-14 |  |
| RES-30 | Aggregate statistics with periods_per_year | Not started |  | Phase 18 |  |
| RES-31 | Documented formula for every statistic | Not started |  | Phase 18 |  |
| RES-40 | Export of snapshots, events, summary and provenance | Not started |  | Phase 18 |  |

## Interfaces (§13)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| INT-1 | `prophetovol serve` | Not started |  | Phase 19 |  |
| INT-2 | Local security: loopback, Host/Origin checks, per-launch token | Not started |  | Phase 19 |  |
| INT-3 | Clean shutdown on Ctrl+C | Not started |  | Phase 19 |  |
| INT-10 | REST API with OpenAPI covering every capability | Not started |  | Phase 20 |  |
| INT-11 | Paged lists with totals; nothing unbounded | **Partial** | Phase 3 (storage and service lists) | API (20) | `contract/test_adapter_contract.py` |
| INT-12 | OpenAPI kept current by a test; generated TypeScript types | Not started |  | Phase 20 |  |
| INT-13 | Non-finite floats encoded as strings | Not started |  | Phase 19 |  |
| INT-20 | Ingest, commit, purge, runs, long pre-flight and exports run as jobs | **Partial** | Phase 4 (job infrastructure), 6 (ingest as a job) | commit and purge (7), long pre-flight (10), runs (14), exports (18) | `unit/test_jobs.py` |
| INT-21 | Job fields and lifecycle | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py`, `unit/test_jobs.py` |
| INT-22 | Jobs persisted in the catalog | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py`, `unit/test_audit.py` |
| INT-23 | Write jobs one at a time in submission order; reads stay responsive | **Done** | Phase 4 |  | `unit/test_jobs.py`, `contract/test_adapter_contract.py` |
| INT-24 | Queued jobs cancellable; running jobs cancelled at safe points | **Partial** | Phase 4 (mechanism), 6 (safe points in ingest) | safe points in runs (14) | `unit/test_jobs.py`, `unit/test_ingest.py` |
| INT-30 | GUI: Home | Not started |  | Phase 21 |  |
| INT-31 | GUI: Data | Not started |  | Phase 21 |  |
| INT-32 | GUI: Strategies | Not started |  | Phase 22 |  |
| INT-33 | GUI: Stress definitions | Not started |  | Phase 22 |  |
| INT-34 | GUI: New run | Not started |  | Phase 23 |  |
| INT-35 | GUI: Run page | Not started |  | Phase 23 |  |
| INT-36 | GUI: Jobs panel | Not started |  | Phase 21 |  |
| INT-37 | Charts as tables; desktop-first layout; browsers | Not started |  | Phase 21-23 |  |
| INT-40 | CLI commands | **Partial** | Phase 1 (group with `--home`, `--version`), 5 (`testdata generate`), 8 (`data`, `registry`, `jobs`, `docs`), 9 (`spec validate|publish|list|show|export`, and `spec examples`) | run (14), stress (16), demo (24) | `unit/test_cli.py`, `unit/test_data_cli.py`, `unit/test_spec_cli.py` |
| INT-41 | CLI and server cannot share a home; both say so with the remedy | **Partial** | Phase 3 (service reports it), 8 (CLI message with the remedy) | server message (19) | `unit/test_service.py`, `unit/test_data_cli.py` |
| INT-50 | Synthetic data generator in the vendor format | **Done** | Phase 5 | also an older-conventions mode (five-character codes, historical roots, Saturday expirations, single price, discounted deltas) | `unit/test_generator.py` |
| INT-51 | `prophetovol demo` | Not started |  | Phase 24 |  |
| INT-52 | Vendor data never committed; tests on synthetic data; optional real-data tests | **Partial** | Phase 1 (`.gitignore`; synthetic-only tests) | optional real-data tests (8, 15) |  |

## Schemas and documentation (§14)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DOC-1 | One pydantic definition per configurable item, every field described | **Partial** | Phase 1 (meta-test), applied in 2-9; 8 (generated reference docs, checked current by a meta-test) | applies to every later model | `meta/test_documentation.py` |
| DOC-2 | Descriptions state units, signs, defaults and interactions | **Partial** | Phase 2-4, 9 (spec and parameter models) | applies to every later model |  |
| DOC-3 | Conventions published as a document generated from the module | **Done** | Phase 2 (conventions module), 8 (`docs/reference/conventions.rst` generated by `docs generate`) |  | `unit/test_conventions.py`, `meta/test_documentation.py` |
| DOC-4 | reST docstrings with Sphinx fields; README coverage | **Partial** | Phase 1 (meta-test enforces docstrings and `:param`), 8 (README: install, test data, import, review, coverage, delete, purge) | README sections for spec, run (14) and demo (24) | `meta/test_documentation.py` |

## Audit (§15)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| AUD-1 | Actor and channel recorded on runs, imports, commits, deletes, purges, definitions | **Partial** | Phase 3, 4, 6, 7 (lifecycle jobs and attempts) | Runs (14) | `unit/test_audit.py`, `unit/test_data_lifecycle.py` |
| AUD-2 | Attempts log of every operation, including rejections | **Partial** | Phase 4, 6, 7 (preview, commit, delete, purge and execution), 9 (spec.validate, spec.publish), 10 (run.preflight, run.save_template) | Each new operation is audited as it is added | `unit/test_audit.py`, `unit/test_data_lifecycle.py` |
| AUD-3 | Software versions recorded on every run | **Partial** | Phase 1 (collector) | recorded on runs (14) | `unit/test_core.py` |
| AUD-4 | Content hashes for definitions and import files | **Done** | Phase 3 (stored), 6 (file hashing at ingest) | specs (9) get hashes through the same `save_definition` | `contract/test_adapter_contract.py`, `unit/test_ingest.py` |

## Distribution (§16.2)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DIST-1 | A standard pure Python wheel | **Partial** | Phase 1 (pure-Python wheel built and tested) | built front end included (24) | `packaging/test_wheel.py` |

## Testing (§17)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| TEST-1 | Golden engine tests | **Partial** | Phase 11 (selection: every expiration selector, nth_expiration across a weekend and a holiday) | book and fills (12), rules (13), stress modes (17) | `unit/test_selection.py` |
| TEST-2 | Invariant tests on many seeded runs | Not started |  | Phase 15 |  |
| TEST-3 | Determinism test | Not started |  | Phase 15 |  |
| TEST-4 | Point-in-time test | **Done** | Phase 10 |  | `unit/test_market_data.py` |
| TEST-5 | Time-convention tests | **Done** | Phase 2 (unit cases incl. DST and Saturday expiries), 5 (generator greeks reproduced exactly), 6 (SQL time to expiry equal to Python for every row), 8 (vendor call deltas reproduced on real 2023 data, median error 3e-7) |  | `unit/test_time.py`, `unit/test_generator.py`, `unit/test_ingest.py`, `realdata/test_vendor_ingest.py` |
| TEST-6 | Ingest tests reproducing real-data quirks | **Done** | Phase 6 |  | `unit/test_ingest.py` |
| TEST-7 | Adapter contract suite | **Partial** | Phase 3, 7 | Atomic run writes (14) | `contract/test_adapter_contract.py`, `contract/test_lifecycle_contract.py` |
| TEST-8 | Validation tests and YAML round trip | Not started |  | Phase 9 |  |
| TEST-9 | API, front-end and end-to-end tests | Not started |  | Phase 19-24 |  |
| TEST-10 | Optional real-data tests | **Partial** | Phase 8 (ingest part: real 2008 and 2023 through the CLI; counts, quality, coverage, derived columns, parity forwards, checkpoint 1 flow) | run part (15); Phase 0 findings recorded in plan §15 | `realdata/test_vendor_ingest.py` |
| TEST-11 | Appendix B acceptance tests | Not started |  | Phase 15 |  |

## Non-functional (§18)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| NFR-1 | Performance targets | **Partial** | Phase 0 (targets agreed; ingest and data access measured), 6 (real 2023: 4.04M rows ingested in 28 s), 8 (2008 and 2023 imported and checked through the CLI in about 60 s together), 10 (the engine's slice: only its columns and the spec's expiry horizon, in three-month chunks) | whole run (15) | `unit/test_market_data.py` |
| NFR-2 | GUI responsiveness | Not started |  | Phase 21-24 |  |
| NFR-3 | Readable expected errors; generic unexpected errors with details logged | **Partial** | Phase 1, 3, 4 (error hierarchy and messages), 8 (CLI: short expected errors; unexpected ones logged to `logs/server.log`), 9 (CLI output never fails on characters a Windows pipe cannot encode) | API presentation (19) | `unit/test_core.py`, `unit/test_service.py`, `unit/test_data_cli.py` |
| NFR-4 | No silent data loss; definitions and runs never edited in place | **Partial** | Phase 3, 4, 7 (confirmed scope; recoverable purge/discard) | Immutable run results (14) | `contract/test_lifecycle_contract.py`, `unit/test_data_lifecycle.py` |
| NFR-5 | Accessibility | Not started |  | Phase 21-24 |  |

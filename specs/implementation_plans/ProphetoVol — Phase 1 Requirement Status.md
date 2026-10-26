# ProphetoVol — Phase 1 Requirement Status

Oct 25, 2026 · @Chuck · **Up to date through plan Phase 4 (jobs and audit).** · Tracks: *ProphetoVol — Phase 1 Requirements Specification* (v6, agreed) against *ProphetoVol — Phase 1 Implementation Plan* (v3, agreed).

One row per requirement ID. This file is updated in every portion of work, in the same change as the code, so each commit carries its own status changes.

- **Done:** nothing is left to build for this requirement.
- **Partial:** some of it is built; *Remaining or notes* says what is left and in which plan phase.
- **Not started:** *Remaining or notes* gives the plan phase that builds it.
- **Done in** names plan phases (the build steps of the implementation plan, not the product phases of the roadmap). Each plan phase is one commit, tagged by the project owner. Phase 0 is the feasibility check.
- Cross-cutting rules (for example DOC-1, AUD-2, TIME-3) stay **Partial** while new code keeps arriving: they are enforced on everything built so far and apply to each new piece.
- *Tests* are paths under `tests/`.

## Summary

**220 requirements:** 14 done, 48 partial, 158 not started.

| Milestone | Plan phases | Status |
| --- | --- | --- |
| **M1 Data foundation** | 1–8 | **In progress:** phases 1–4 done (Oct 25, 2026); 5 (synthetic data), 6 (ingest), 7 (versions, delete, purge, coverage), 8 (data CLI, checkpoint 1) to go |
| **M2 Engine core** | 9–15 | Not started |
| **M3 Stress and analytics** | 16–18 | Not started |
| **M4 Server and GUI** | 19–24 | Not started |

| Plan phase | Content | Completed |
| --- | --- | --- |
| 0 | Feasibility check | Oct 25, 2026 |
| 1 | Repository foundation | Oct 25, 2026 |
| 2 | Conventions, time, calendar and registries | Oct 25, 2026 |
| 3 | Storage adapter and catalog | Oct 25, 2026 |
| 4 | Jobs and audit | Oct 25, 2026 |
| 5 | Synthetic data generator | — |
| 6 | Ingest, normalization, validation and quality reports | — |
| 7 | Overlap, commit, versions, delete, purge, invalidation and coverage | — |
| 8 | Data CLI, documentation and checkpoint 1 | — |
| 9–24 | M2–M4 (see the implementation plan, §7–§9) | — |

| Area | Done | Partial | Not started |
| --- | --- | --- | --- |
| Architecture (§4) | 2 | 2 | 3 |
| Time, steps and snapshots (§5.1) | 0 | 1 | 2 |
| Versioning (§5.3) | 0 | 3 | 1 |
| Conventions (§5.4) | 0 | 9 | 0 |
| Registries (§5.5) | 1 | 2 | 1 |
| Data module (§6) | 1 | 8 | 20 |
| Reference data (§7) | 7 | 1 | 0 |
| Strategy specification (§8) | 0 | 0 | 50 |
| Engine (§9) | 0 | 0 | 19 |
| Stress module (§10) | 0 | 0 | 18 |
| Runs (§11) | 0 | 2 | 9 |
| Results and analytics (§12) | 0 | 0 | 8 |
| Interfaces (§13) | 3 | 6 | 16 |
| Schemas and documentation (§14) | 0 | 4 | 0 |
| Audit (§15) | 0 | 4 | 0 |
| Distribution (§16.2) | 0 | 1 | 0 |
| Testing (§17) | 0 | 2 | 9 |
| Non-functional (§18) | 0 | 3 | 2 |

## Architecture (§4)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| ARC-1 | BacktestService is the only component that opens storage; clients are thin | **Partial** | Phase 3 | CLI commands (8), API (19-20) built as thin clients | `unit/test_service.py` |
| ARC-2 | The engine is a pure library with no I/O | Not started |  | Phase 9-13 |  |
| ARC-3 | Point-in-time access through MarketDataView, enforced in code | Not started |  | Phase 10 |  |
| ARC-4 | One writer: service owns read-write connections; write jobs one at a time; readers on cursors | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py` (readers), `unit/test_jobs.py` |
| ARC-5 | Extensible component types are registries of named implementations | **Partial** | Phase 2 | remaining registries (9, 11-13, 16) | `unit/test_registry.py` |
| ARC-6 | Single-user, local server bound to 127.0.0.1 | Not started |  | Phase 19 |  |
| ARC-7 | Names: ProphetoVol; package and CLI `prophetovol`; home `~/.prophetovol` | **Done** | Phase 1 |  | `unit/test_package.py`, `packaging/test_wheel.py`, `unit/test_core.py` |

## Time, steps and snapshots (§5.1)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| TIME-1 | A run advances in steps with as-of timestamps; frequency is configuration | Not started |  | Phase 10, 13 (Frequency enum exists from 2) |  |
| TIME-2 | Four snapshot kinds: market, position, portfolio, stress | Not started |  | Phase 6, 12, 16 |  |
| TIME-3 | Time quantities are named by their units | **Partial** | Phase 2, 3 | applies to every later field; checked in each phase | `unit/test_time.py` |

## Versioning (§5.3)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| VER-1 | Published definitions are immutable; every change is a new integer version | **Partial** | Phase 3, 4 | strategy specs (9), stress definitions (16) | `contract/test_adapter_contract.py`, `unit/test_audit.py` |
| VER-2 | Each published version stores a content hash of its canonical JSON | **Partial** | Phase 3 | specs (9), stress definitions (16) | `contract/test_adapter_contract.py` |
| VER-3 | A run records by reference everything it used | Not started |  | Phase 14 |  |
| VER-4 | Market snapshots are versioned per (underlying, as_of) | **Partial** | Phase 3 | activation and replacement (7) | `contract/test_adapter_contract.py` |

## Conventions (§5.4)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| CONV-1 | Time to expiry: calendar minutes on the exchange clock over 365 days | **Partial** | Phase 2 | stored per row at ingest (6); used by engine and stress (12-17) | `unit/test_time.py` |
| CONV-2 | Trading days to expiry: after the as-of date through the settlement date | **Partial** | Phase 2 | stored at ingest (6); used by selectors and triggers (11, 13) | `unit/test_time.py` |
| CONV-3 | Settlement date, expiry and last trading day (incl. Saturday-dated) | **Partial** | Phase 2 | stored at ingest (6); forced closes (13) | `unit/test_time.py` |
| CONV-4 | Delta targets are absolute values | **Partial** | Phase 2 (published text) | delta selectors (11) | `unit/test_conventions.py` |
| CONV-5 | At the money means 50 delta of the leg's own type | **Partial** | Phase 2 (published text) | `atm` selector (11) | `unit/test_conventions.py` |
| CONV-6 | Trades execute at the step where the trigger is observed | **Partial** | Phase 2 (published text) | engine (12-13) | `unit/test_conventions.py` |
| CONV-7 | Dollar greek formulas | **Partial** | Phase 2 (formulas) | position snapshots (12) | `unit/test_conventions.py` |
| CONV-8 | Signs: positive quantity is long; positive cash flow is received | **Partial** | Phase 2 (published text) | accounting (12) | `unit/test_conventions.py` |
| CONV-9 | A roll re-establishes the structure by default | **Partial** | Phase 2 (published text) | rolls (13) | `unit/test_conventions.py` |

## Registries (§5.5)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| REG-1 | The Phase 1 registries and their implementations | **Partial** | Phase 2 (settlement_source) | selectors, schedules, conditions, actions, hedge, sizing, fills, constructor (9, 11-13); stress types and modes (16-17) | `unit/test_registry.py` |
| REG-2 | Every implementation declares name, description, documented parameter model, version | **Done** | Phase 2 | enforced at registration for every future implementation | `unit/test_registry.py` |
| REG-3 | Registries are discoverable with descriptions and JSON Schemas | **Partial** | Phase 2 (service level) | CLI `registry list/show` (8), API (20) | `unit/test_registry.py` |
| REG-4 | Condition types are pluggable | Not started |  | Phase 13 |  |

## Data module (§6)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DATA-1 | Input is the 22-column ivolatility CSV | Not started |  | Phase 6 |  |
| DATA-2 | Date format, `*` flag, and both option symbol formats | Not started |  | Phase 6 |  |
| DATA-3 | One underlying per import, from one or more files | Not started |  | Phase 6 |  |
| DATA-4 | Imports accept several CSVs, folders or zips; size limit | Not started |  | Phase 6 |  |
| DATA-10 | Uploads are streamed; ingest runs as a job with progress | Not started |  | Phase 6 (job infrastructure ready from 4) |  |
| DATA-11 | Ingest validates and normalizes into staged Parquet under a new import id | **Partial** | Phase 3 (staged storage) | ingest pipeline (6) | `contract/test_adapter_contract.py` |
| DATA-12 | Each file's SHA-256 is recorded; duplicate files are reported | **Partial** | Phase 3 (storage and lookup) | hashing on upload and reporting (6) | `contract/test_adapter_contract.py` |
| DATA-13 | Normalization rules and derived columns computed at ingest | Not started |  | Phase 6 |  |
| DATA-14 | The forward: vendor per-series from 2018-06-25, parity fit before | Not started |  | Phase 6 |  |
| DATA-20 | Validation checks and the quality report | Not started |  | Phase 6 |  |
| DATA-21 | Quality report viewable in GUI and CLI, kept permanently | Not started |  | Phase 6, 8 (CLI), 21 (GUI) |  |
| DATA-30 | Overlap with active data shown before commit | Not started |  | Phase 7 |  |
| DATA-31 | Commit choices: replace, add new dates only, cancel | Not started |  | Phase 7 (cancel = discard, storage ready from 3) |  |
| DATA-32 | Commit is atomic | Not started |  | Phase 7 |  |
| DATA-33 | Committing or replacing data queues invalidation | Not started |  | Phase 7 |  |
| DATA-40 | At most one active version per (underlying, as_of); superseded kept until purge | **Partial** | Phase 3 (version records and states) | activation and supersession (7) | `contract/test_adapter_contract.py` |
| DATA-41 | Version registry in the catalog, contents in Parquet; identity (underlying, as_of, import_id) | **Done** | Phase 3 |  | `contract/test_adapter_contract.py` |
| DATA-50 | Delete by underlying and range deactivates versions | Not started |  | Phase 7 |  |
| DATA-51 | Purge removes superseded or deleted data and reclaims space | Not started |  | Phase 7 |  |
| DATA-52 | Affected runs listed and confirmed before delete or purge | Not started |  | Phase 7 |  |
| DATA-53 | Delete and purge recorded in the audit trail | Not started |  | Phase 7 (audit mechanism ready from 4) |  |
| DATA-60 | Runs that read changed data are flagged data superseded | Not started |  | Phase 7 |  |
| DATA-61 | The data-superseded flag is visible on runs and in the API | Not started |  | Phase 7, 14, 20, 23 |  |
| DATA-70 | Coverage view per trading day | Not started |  | Phase 7; 8 (CLI), 21 (GUI) |  |
| DATA-80 | Parquet layout per underlying/year/month, one file per import; active-version filtering | **Partial** | Phase 3 (layout) | active-version filtering on reads (7, 10) | `contract/test_adapter_contract.py`, `unit/test_duckdb_storage.py` |
| DATA-81 | Reads go through Ibis | **Partial** | Phase 3 (all catalog reads) | market reads (7, 10), results reads (14) | `contract/test_adapter_contract.py` |
| DATA-82 | Writes go through the StorageAdapter interface | **Partial** | Phase 3 | commit, deactivate, purge (7), market view (10), run results (14) | `contract/test_adapter_contract.py` |
| DATA-83 | Physical layout is known only to the adapter | **Partial** | Phase 3 | holds for each operation added in 7, 10, 14 | `contract/test_adapter_contract.py` |
| DATA-84 | Adapter contract test suite | **Partial** | Phase 3 (Phase 3 cases) | overlap, replace, add-new-only, delete, purge, point-in-time (7); run writes (14) | `contract/test_adapter_contract.py` |

## Reference data (§7)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| REF-1 | Underlying configuration with expiry times and all vendor roots | **Done** | Phase 2, 3 (seeded) |  | `unit/test_reference.py`, `unit/test_service.py` |
| REF-2 | Underlying configurations are editable as versioned definitions | **Done** | Phase 3, 4 |  | `unit/test_service.py`, `unit/test_audit.py` |
| REF-5 | Data source configuration and timing | **Done** | Phase 2, 3 (seeded) |  | `unit/test_reference.py` |
| REF-6 | Timing confirmed on real data; held in configuration | **Done** | Phase 0 (confirmed), 2 (configuration) |  | `unit/test_reference.py` |
| REF-10 | NYSE trading calendar from exchange_calendars | **Done** | Phase 2 |  | `unit/test_calendar.py` |
| REF-11 | The calendar version is recorded on runs | **Partial** | Phase 2 (version available) | recorded on runs (14) | `unit/test_calendar.py` |
| REF-20 | Settlement-source registry with pm_index_close | **Done** | Phase 2 |  | `unit/test_registry.py` |
| REF-21 | No AM settlement source; AM contracts never held to expiry | **Done** | Phase 2 | the forced close itself is SPEC-51 (13) | `unit/test_registry.py` |

## Strategy specification (§8)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| SPEC-1 | StrategySpec contents | Not started |  | Phase 9 |  |
| SPEC-2 | Leg fields | Not started |  | Phase 9 |  |
| SPEC-3 | Leg references without cycles, resolved in dependency order | Not started |  | Phase 9 |  |
| SPEC-4 | Selection is atomic across legs | Not started |  | Phase 11 |  |
| SPEC-10 | `target_days` expiration selector | Not started |  | Phase 11 |  |
| SPEC-11 | `trading_days_out` expiration selector | Not started |  | Phase 11 |  |
| SPEC-12 | `nth_expiration` expiration selector | Not started |  | Phase 11 |  |
| SPEC-13 | `same_as_leg` and `next_after_leg` selectors | Not started |  | Phase 11 |  |
| SPEC-14 | Expiration filters | Not started |  | Phase 11 |  |
| SPEC-15 | Expirations never eligible at/after expiry; AM never on/after last trading day | Not started |  | Phase 11 |  |
| SPEC-20 | `delta` strike selector | Not started |  | Phase 11 |  |
| SPEC-21 | `atm` strike selector | Not started |  | Phase 11 |  |
| SPEC-22 | `forward` strike selector | Not started |  | Phase 11 (forward column from 6) |  |
| SPEC-23 | `same_strike_as` strike selector | Not started |  | Phase 11 |  |
| SPEC-24 | `strike_offset` strike selector | Not started |  | Phase 11 |  |
| SPEC-25 | No-match handling | Not started |  | Phase 11 |  |
| SPEC-26 | Selection uses only eligible contracts | Not started |  | Phase 11 |  |
| SPEC-27 | Delta selection uses vendor delta; null delta not eligible | Not started |  | Phase 11 |  |
| SPEC-28 | Quote filters | Not started |  | Phase 11 |  |
| SPEC-30 | `once` entry schedule | Not started |  | Phase 11 |  |
| SPEC-31 | `when_flat` entry schedule with cooldown | Not started |  | Phase 11 |  |
| SPEC-32 | `every_n_trading_days` entry schedule | Not started |  | Phase 11 |  |
| SPEC-33 | `weekdays` entry schedule | Not started |  | Phase 11 |  |
| SPEC-34 | `max_open` for schedules | Not started |  | Phase 11 |  |
| SPEC-35 | Failed entries retried at the next scheduled step | Not started |  | Phase 11 |  |
| SPEC-40 | Trigger structure | Not started |  | Phase 13 |  |
| SPEC-41 | Phase 1 trigger conditions | Not started |  | Phase 13 |  |
| SPEC-42 | Condition evaluation; null greeks evaluate false | Not started |  | Phase 13 |  |
| SPEC-43 | Close and roll actions | Not started |  | Phase 13 |  |
| SPEC-44 | One action per structure per step, with precedence | Not started |  | Phase 13 |  |
| SPEC-45 | Roll whose opening side fails selection | Not started |  | Phase 13 |  |
| SPEC-46 | Structure P&L per unit | Not started |  | Phase 13 |  |
| SPEC-50 | PM-settled legs settle at intrinsic value | Not started |  | Phase 13 (pm_index_close ready from 2) |  |
| SPEC-51 | AM-settled legs force-closed on their last trading day | Not started |  | Phase 13 |  |
| SPEC-52 | Validation rejects holding AM-settled legs to expiration | Not started |  | Phase 13 |  |
| SPEC-53 | Validation warns when the engine will force-close an AM leg | Not started |  | Phase 13 |  |
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
| SPEC-80 | Dry-run validation with field paths | Not started |  | Phase 9 |  |
| SPEC-81 | Authoring and exact YAML round trip | Not started |  | Phase 9; GUI editor 22 |  |
| SPEC-82 | Appendix B examples ship as sample specs | Not started |  | Phase 9 |  |

## Engine (§9)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| ENG-1 | The step loop and its nine steps in order | Not started |  | Phase 13 |  |
| ENG-2 | The constructor interface; `rules` constructor | Not started |  | Phase 13 |  |
| ENG-3 | Several structures of one spec tracked separately | Not started |  | Phase 13 |  |
| ENG-4 | Time-dependent calculations from timestamps and calendar, never step counts | Not started |  | Phase 10-13 (time functions ready from 2) |  |
| ENG-10 | Determinism | Not started |  | Phase 12-15 |  |
| ENG-20 | Valid quotes and the mid | Not started |  | Phase 12 |  |
| ENG-21 | Marking, stale marks and warnings | Not started |  | Phase 12 |  |
| ENG-22 | Final marks of settled and force-closed legs | Not started |  | Phase 12 |  |
| ENG-23 | The series forward used for the forward selector and stress | Not started |  | Phase 11, 16 (column from 6) |  |
| ENG-24 | Greeks are the vendor's | Not started |  | Phase 12 |  |
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
| STR-20 | Black-76 revaluation on the series forward | Not started |  | Phase 16 |  |
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
| RUN-1 | Run definition and configuration fields | Not started |  | Phase 10 |  |
| RUN-2 | Configuration templates; full resolved configuration and hash stored | Not started |  | Phase 10, 14 |  |
| RUN-10 | Pre-flight checks | Not started |  | Phase 10 |  |
| RUN-11 | Pre-flight reports all problems; missing days; fixes the step schedule | Not started |  | Phase 10 |  |
| RUN-12 | Pre-flight available on its own | Not started |  | Phase 10 |  |
| RUN-20 | Run statuses; runs left queued or running marked failed (interrupted) | **Partial** | Phase 4 (recovery pattern for jobs) | run statuses and recovery of interrupted runs (14) | `unit/test_jobs.py` |
| RUN-21 | Run progress: steps done of total, with current as-of | Not started |  | Phase 14 (job progress ready from 4) |  |
| RUN-22 | Cancellation at the next step boundary keeps results | Not started |  | Phase 14 (cooperative cancellation ready from 4) |  |
| RUN-23 | Results written in one transaction when the run ends | Not started |  | Phase 14 |  |
| RUN-30 | Recorded provenance of a run | **Partial** | Phase 1 (software versions collector) | provenance recorded on runs (14) | `unit/test_core.py` |
| RUN-40 | Runs flagged data superseded | Not started |  | Phase 7, 14 |  |

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
| INT-20 | Ingest, commit, purge, runs, long pre-flight and exports run as jobs | **Partial** | Phase 4 (job infrastructure) | each operation as a job (6, 7, 10, 14, 18) | `unit/test_jobs.py` |
| INT-21 | Job fields and lifecycle | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py`, `unit/test_jobs.py` |
| INT-22 | Jobs persisted in the catalog | **Done** | Phase 3, 4 |  | `contract/test_adapter_contract.py`, `unit/test_audit.py` |
| INT-23 | Write jobs one at a time in submission order; reads stay responsive | **Done** | Phase 4 |  | `unit/test_jobs.py`, `contract/test_adapter_contract.py` |
| INT-24 | Queued jobs cancellable; running jobs cancelled at safe points | **Partial** | Phase 4 (mechanism) | safe points in ingest (6) and runs (14) | `unit/test_jobs.py` |
| INT-30 | GUI: Home | Not started |  | Phase 21 |  |
| INT-31 | GUI: Data | Not started |  | Phase 21 |  |
| INT-32 | GUI: Strategies | Not started |  | Phase 22 |  |
| INT-33 | GUI: Stress definitions | Not started |  | Phase 22 |  |
| INT-34 | GUI: New run | Not started |  | Phase 23 |  |
| INT-35 | GUI: Run page | Not started |  | Phase 23 |  |
| INT-36 | GUI: Jobs panel | Not started |  | Phase 21 |  |
| INT-37 | Charts as tables; desktop-first layout; browsers | Not started |  | Phase 21-23 |  |
| INT-40 | CLI commands | **Partial** | Phase 1 (group with `--home`, `--version`) | data and registry (8), spec and run (14), stress (16), demo (24) | `unit/test_cli.py` |
| INT-41 | CLI and server cannot share a home; both say so with the remedy | **Partial** | Phase 3 (service reports it) | CLI (8) and server (19) messages | `unit/test_service.py` |
| INT-50 | Synthetic data generator in the vendor format | Not started |  | Phase 5 |  |
| INT-51 | `prophetovol demo` | Not started |  | Phase 24 |  |
| INT-52 | Vendor data never committed; tests on synthetic data; optional real-data tests | **Partial** | Phase 1 (`.gitignore`; synthetic-only tests) | optional real-data tests (8, 15) |  |

## Schemas and documentation (§14)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DOC-1 | One pydantic definition per configurable item, every field described | **Partial** | Phase 1 (meta-test), applied in 2-4 | applies to every later model; generated reference docs (8) | `meta/test_documentation.py` |
| DOC-2 | Descriptions state units, signs, defaults and interactions | **Partial** | Phase 2-4 | applies to every later model |  |
| DOC-3 | Conventions published as a document generated from the module | **Partial** | Phase 2 (conventions module) | generated document (8) | `unit/test_conventions.py` |
| DOC-4 | reST docstrings with Sphinx fields; README coverage | **Partial** | Phase 1 (meta-test enforces docstrings and `:param`) | README sections for demo, import, spec, run (8, 14, 24) | `meta/test_documentation.py` |

## Audit (§15)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| AUD-1 | Actor and channel recorded on runs, imports, commits, deletes, purges, definitions | **Partial** | Phase 3, 4 (definitions, imports, jobs, attempts) | commits, deletes, purges (7), runs (14) | `contract/test_adapter_contract.py`, `unit/test_audit.py` |
| AUD-2 | Attempts log of every operation, including rejections | **Partial** | Phase 4 (mechanism; publishing, job cancel) | each new operation is audited as it is added | `unit/test_audit.py` |
| AUD-3 | Software versions recorded on every run | **Partial** | Phase 1 (collector) | recorded on runs (14) | `unit/test_core.py` |
| AUD-4 | Content hashes for definitions and import files | **Partial** | Phase 3 (stored) | file hashing at upload (6); specs (9) | `contract/test_adapter_contract.py` |

## Distribution (§16.2)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DIST-1 | A standard pure Python wheel | **Partial** | Phase 1 (pure-Python wheel built and tested) | built front end included (24) | `packaging/test_wheel.py` |

## Testing (§17)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| TEST-1 | Golden engine tests | Not started |  | Phase 11-13, 17 (chains from 5) |  |
| TEST-2 | Invariant tests on many seeded runs | Not started |  | Phase 15 |  |
| TEST-3 | Determinism test | Not started |  | Phase 15 |  |
| TEST-4 | Point-in-time test | Not started |  | Phase 10 |  |
| TEST-5 | Time-convention tests | **Partial** | Phase 2 (unit cases incl. DST and Saturday expiries) | generator greeks (5), SQL vs Python per row (6), vendor deltas on real data (8) | `unit/test_time.py` |
| TEST-6 | Ingest tests reproducing real-data quirks | Not started |  | Phase 6 |  |
| TEST-7 | Adapter contract suite | **Partial** | Phase 3 (Phase 3 cases) | 7, 14 | `contract/test_adapter_contract.py` |
| TEST-8 | Validation tests and YAML round trip | Not started |  | Phase 9 |  |
| TEST-9 | API, front-end and end-to-end tests | Not started |  | Phase 19-24 |  |
| TEST-10 | Optional real-data tests | Not started |  | Phase 8, 15 (findings from Phase 0 recorded in plan §15) |  |
| TEST-11 | Appendix B acceptance tests | Not started |  | Phase 15 |  |

## Non-functional (§18)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| NFR-1 | Performance targets | **Partial** | Phase 0 (targets agreed in plan §12; ingest and data access measured) | confirmed in 8 (ingest) and 15 (whole run) |  |
| NFR-2 | GUI responsiveness | Not started |  | Phase 21-24 |  |
| NFR-3 | Readable expected errors; generic unexpected errors with details logged | **Partial** | Phase 1, 3, 4 (error hierarchy and messages) | CLI (8) and API (19) presentation | `unit/test_core.py`, `unit/test_service.py` |
| NFR-4 | No silent data loss; definitions and runs never edited in place | **Partial** | Phase 3, 4 (immutable definitions, append-only attempts, discard only staged) | delete and purge with confirmation (7), runs (14) | `contract/test_adapter_contract.py`, `unit/test_duckdb_storage.py` |
| NFR-5 | Accessibility | Not started |  | Phase 21-24 |  |

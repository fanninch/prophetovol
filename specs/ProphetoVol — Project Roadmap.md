# ProphetoVol — Project Roadmap

Oct 25, 2026 · @Chuck · v7 (Phase 1 requirements v7: internal conventions and data-source adapters)

> **What is being built: Phase 1 only, as defined by *ProphetoVol — Phase 1 Requirements Specification* (v7, agreed) and its implementation plan.** Where this roadmap and the Phase 1 specification differ, the specification governs.
>
> **Everything about Phases 2 and later is roadmap, not yet specified.** It records the design discussion so far, so later phases start with the reasoning that shaped them. Nothing in those sections is being implemented. Phases may be reordered, merged or dropped, and each gets its own agreed requirements specification and implementation plan before it is built.

## 1. Vision

A research and backtesting application for index options in which a user can describe what they want to test, in trading language, and get a correct, reproducible answer.

It is built in layers:

1. **A deterministic backtesting tool** (Phase 1): data, strategy specifications, a daily engine, stress tests and analytics.
2. **An AI layer** (Phase 2): given a request or a statement, the AI decides what to test, builds the specifications, runs them through the deterministic tool, and explains the results.
3. **Research capabilities** (Phase 3 onward): market context, forecasts, portfolio construction, walk-forward testing and a research agent, all running on the same deterministic core.

The intended product is commercial, starting as a single-user local application and designed so it can later be hosted.

## 2. Guiding Principles

These held throughout the discussion and should carry into every phase.

1. **The AI proposes; deterministic code computes.** No number reported to the user is produced by a language model. The AI chooses what to test, translates descriptions into specifications, and interprets results; the engine, pricer, stress module and analytics compute.
2. **No private path for the AI.** The agent calls the same service operations as the GUI and the CLI. Anything it can do, a person can do through a form or a script.
3. **One schema per configurable item.** Validation, the API, the GUI forms, the documentation and what the agent reads all come from the same field-described schema. This is what makes the system usable by an AI later.
4. **Point-in-time, always.** Nothing in a simulation may see data dated after the simulation day, enforced in code rather than by convention.
5. **Reproducible by construction.** Every result references immutable, versioned inputs: data versions, specification versions, configuration, and software versions.
6. **Plug-in components.** Selectors, conditions, actions, hedge rules, sizing, fills, settlement sources, stress scenarios, forecasters and constructors are registries. New capability means a new implementation, not an engine change.
7. **Database-portable.** DuckDB first; reads through Ibis, writes through a storage-adapter interface with a contract test suite, so other databases can be added.
8. **Start simple, leave stubs.** Each phase ships the simplest version that works end to end, with interfaces in place for the richer versions.

## 3. Phase Summary

| Phase | Theme | Main deliverables | Status |
| --- | --- | --- | --- |
| **1** | Deterministic backtester | Data module, strategy specs, daily engine, underlying-slide stress, results and statistics, CLI, API, GUI | **Being built.** Requirements (v7) and implementation plan (v5, M2 detailed) agreed; plan phases 0–8 of 24 done (M1 complete, checkpoint 1 held). Progress per requirement: *ProphetoVol — Phase 1 Requirement Status* |
| **2** | AI test assistant | Strategy-building chat; AI that decides what to test from a request; batch runs and comparisons | Roadmap — not yet specified |
| **3** | Market context, richer rules and risk | Market-context snapshots, conditions on context, P&L attribution, more stress scenario types, more risk limits, AM settlement table | Roadmap — not yet specified |
| **4** | Forecasting | Forecast object and record, static forecasters, forecast scoring | Roadmap — not yet specified |
| **5** | Portfolio construction & walk-forward | Constructor framework, objective and constraints, trading-cost-aware rebalancing, the daily walk-forward loop, process analytics | Roadmap — not yet specified |
| **6** | Research agent & scenario tools | Experiment ledger, regime analysis, sentinel positions, realized-vs-implied scenario grid, research agent | Roadmap — not yet specified |
| **Trial** | Trial distribution | Time-limited, protected wheel for prospective clients | Not planned; Phase 1 ships a standard pure Python wheel |
| **Later** | Hosted & commercial | Multi-user hosting, other databases, vendor-hosted data, MCP server, more underlyings | Ideas |

## 4. Phase 1 — Deterministic Backtester (being built)

Fully specified in *ProphetoVol — Phase 1 Requirements Specification* (v7, agreed), which is authoritative. In brief (the package and CLI are `prophetovol`):

- **Data:** upload of ivolatility files; validation and quality reports; overlap handling (replace, add new dates only, cancel); data versions; delete and purge; coverage; trading calendar; settlement-source plug-in point.
- **Strategies:** legs with expiration and strike selectors (delta, at the money as 50 delta, forward, references to other legs); entry schedules; triggers (condition, scope, action) for rolls and closes; expiration handling; delta-hedge bands; sizing by contracts or notional.
- **Time and snapshots:** a run advances in steps, each with an as-of timestamp; results are position, portfolio and stress snapshots. Phase 1 has one frequency (end of day), but no names or rules assume one step per day. Time to expiry is a year fraction from timestamps, in calendar time over 365 days, which matches the vendor's greeks (inferred from the samples: a 16:15 ET snapshot, PM expiries at 16:00 ET, AM expiries at 09:30 ET). Selection and triggers state their units: fractional calendar days, trading days, or nth expiration, so dailies work as naturally as monthlies.
- **Engine:** a pure, point-in-time step loop; same-step execution (the close, for end-of-day data); fill models and costs; accounting with reconciliation invariants; AM-settled contracts always closed on their last trading day.
- **Stress:** an underlying slide revalued with Black-76 at sticky strike; modes Monitor, Scale to limit and Halt run.
- **Results:** position, structure and portfolio snapshots at every step, stress snapshots, events, and aggregate statistics (annualized from the frequency's periods per year).
- **Platform:** the data profiling tool's stack; persisted jobs; audit of actor, channel, software versions and rejected attempts; distributed as a standard pure Python wheel, with no compilation, obfuscation or license check (Phase 1 v4).

## 5. Phase 2 — AI Test Assistant (roadmap — not yet specified)

**Goal:** given a request or a statement, the AI decides what to test, builds the specifications, runs them, and explains the results, using only the deterministic tool.

### 5.1 Strategy-building chat

The original feature idea: the user describes a strategy in jargon or leg by leg; the agent translates it into a `StrategySpec`.

- **Clarifying questions come from the schema.** Each spec field carries one of three labels:
  - **Always ask:** no safe default exists (for example, how a multi-expiration structure is rolled, or whether to roll at all).
  - **Default and state:** use the default and say so in the confirmation (for example, fill model or hedge frequency).
  - **Ask if ambiguous:** ask only when the description allows several readings (for example, which options form a butterfly's wings).

  The validation tool returns these labels, so the questions are consistent from run to run rather than left to the model's judgment.
- **Confirmation before running:** the agent shows its understanding in plain English alongside the editable spec.
- **A conventions document** in the agent's context records trading meanings: at the money is 50 delta; "30 delta" is 0.30; "45 day" is calendar days; a roll re-establishes the whole structure unless told otherwise; trades execute at the triggering close. The conventions are the place where trading experience is encoded, and are editable by a trader rather than a developer.
- **Known judgment points** the agent should raise: butterfly wings built from puts and calls are asymmetric because of skew; the default for roll handling on spreads is re-establishing the whole spread, but users will have opinions.

### 5.2 Deciding what to test

The user states a hypothesis or a question ("does selling 25-delta puts work better when vol is high?"); the agent designs a set of runs (variations of a spec, date ranges, stress settings), runs them, and reports what the results show and how strong the evidence is.

- **Agent tools** (thin wrappers over service operations): describe available data; validate an unpublished spec (returning missing, defaulted and conflicting fields); start a run; check status; fetch results and statistics; compare runs.
- **The AI sets configuration from documentation:** for example, it chooses the stress mode (Monitor, Scale to limit, Halt run) from the schema descriptions. Phase 1's field-level descriptions exist for this reason.
- **Overfitting guardrails** apply as soon as the agent can run many variations: every run tagged with the experiment it belongs to, runs never deleted, and the number of variations tried reported alongside any result (see Phase 6).

### 5.3 Enabling work

- **Batch runs and parameter sweeps,** run in parallel worker processes. The engine is a pure library (Phase 1, ARC-2), so workers compute while only the service writes. Sweep results may store only daily portfolio series and summaries, with full detail produced on demand; this is where Parquet for results may come back.
- **Run comparison** views and API.
- **An MCP server** over the same tool surface is a cheap addition once the tools exist.

## 6. Phase 3 — Market Context, Richer Rules and Risk (roadmap — not yet specified)

### 6.1 Market-context snapshots (step 1a of the research loop)

Computed at ingest from the market snapshots, one market-context snapshot per step, every value point-in-time. Phase 1's data module already plans for this: context snapshots record the data version and calculation version they came from; replacing data invalidates context for the changed dates and every later date whose lookback includes them; a pre-flight over the whole window reports gaps up front.

**Must have** (from the vendor data alone):

- surface summary: at-the-money vol at fixed tenors (7, 30, 60, 90, 180 days), skew per tenor (25-delta put and call against the money, 10-delta put), curvature, term slope
- changes over 1, 5 and 20 days
- percentiles of each measure against its own history up to that date
- model-free implied variance (a VIX-style calculation across the chain)
- realized vol over 10, 20, 30, 60 and 90 days, close to close
- implied minus realized at matched tenors
- index returns, drawdown from the high, distance from moving averages
- implied carry from put-call parity
- calendar: days to each expiration; monthly, quarterly and AM-settlement dates
- volume and open interest by strike

**Nice to have** (cheap outside data): VIX futures curve; VIX9D, VIX3M, VVIX; economic calendar (FOMC, CPI, payrolls); rates and credit spreads (vintage data, such as ALFRED, to avoid revisions); implied correlation; other index vols.

**Dream state:** intraday prices; dealer gamma estimates; signed customer flow; news and sentiment with strict timestamps; positioning data.

From Jun 25, 2018 the vendor's "stock price for iv" is the per-series forward (each series has its own, since futures exist only quarterly), so it supplies forward and carry directly. Before that date it is one price per date, and Phase 1 derives each expiration's forward from put-call parity (Phase 1 requirements v6, DATA-14).

### 6.2 Conditions on market context

Phase 1 makes trigger conditions a registry; Phase 3 adds conditions that read the context snapshots, for example "enter only when 30-day implied is at least 3 points over realized." This uses a small restricted vocabulary (named fields, comparisons, all/any), never arbitrary code, as with the profiling tool's FB-13. It also lets the same strategy be run with and without a market filter, which measures what the filter is worth.

### 6.3 P&L attribution

Each period's P&L split into delta, gamma, vega and theta, with an unexplained residual, from the greeks stored in the position snapshots.

### 6.4 Stress and risk extensions

- **More scenario types:** parallel vol shocks; skew steepening and flattening; joint spot-and-vol scenarios (a crash with vol up, not down); historical replays of real episodes (October 2008, February 2018, March 2020) applied to today's book. Each scenario's surface change should be defined explicitly rather than by a model, so there is no ambiguity about what was tested.
- **Full revaluation** remains the rule; greek approximations are wrong at 20% moves.
- **Multi-horizon stress** (a holding period as well as one day), so positions like long-dated wings don't look riskless.
- **More limits:** dollar greek budgets by tenor bucket; concentration per expiration; P&L volatility.
- **Drawdown-scaled risk budget:** the stress budget shrinks with drawdown from the high-water mark (for example 100% at the high, 75% at −5%, 50% at −10%, configurable), with a gradual recovery rule. It shrinks limits rather than forcing trades.
- **Liquidity filters and tradable-universe settings,** configurable per underlying.

### 6.5 AM settlement values

A user-uploaded SET table, as a second settlement source, would allow AM-settled contracts to be held to expiration. The vendor does not supply SET values; Cboe publishes them.

## 7. Phase 4 — Forecasting (roadmap — not yet specified)

Step 1b and 1c of the research loop.

### 7.1 What the forecast is

- **Contents:** realized vol over the horizon, surface moves (level, skew, term structure), and the index's distribution, especially its tails. For skew trades, what matters is realized vol where each option's gamma sits, so the contents must be **joint**: each scenario pairs an index path with the surface's response along it.
- **Form:** probability-weighted scenarios. Step 2 can price candidate books directly against them, stress tests are already scenarios, and human summaries (median and range) fall out of them.
- **Horizons:** configurable; one day minimum; 22 trading days (about a month) as the default long horizon.
- **Relative to the market:** the surface is the market's forecast, so the forecast is also expressed against implied ("expected realized 4 points below 30-day implied").

### 7.2 First forecasters (stubs for the rest)

Building realistic synthetic surfaces is hard and error-prone (arbitrage, tails), so the first forecaster never builds one:

- **Static forecast:** each listed contract keeps today's implied vol (sticky strike by default; sticky delta configurable). There is no surface model, no interpolation and no extrapolation.
- **Index distribution: filtered historical simulation** (the default). Each past daily return is divided by the realized vol at that time, then rescaled by today's forecast realized vol, and the distribution is centered on the forward so it carries no directional view. Samples are used directly as equally weighted scenarios; 22-day paths are built from blocks of consecutive standardized days so vol clustering survives. The lookback defaults to all history before the run date, with a minimum history (for example 500 days) below which forecasts are flagged. This recognizes that part of the skew is fair crash compensation, so the optimizer doesn't treat all skew as mispricing. A lognormal option is also offered.
- **Persistence version:** forecast realized vol is trailing realized (window configurable, default 22 days). This carries one opinion, that recent realized vol persists.
- **Market-implied version:** realized equals implied; every option is fair by construction. This is the null benchmark, not a trading forecaster.
- **Decisions use the one-day horizon at first.** Hedged multi-day P&L depends on the path; because steps 1 and 2 run daily, step 2 can decide on one-day expected P&L and decide again tomorrow. The 22-day forecast is still produced and recorded.
- **Stubs for later:** statistical forecasters (for example HAR-type realized vol models, skew mean reversion), LLM forecasts with structured justifications (claim, cited context figures, evidence against, confidence), hybrid (model baseline, bounded agent adjustment, logged and evaluated separately), user overrides, parameterized surface models, joint index-and-surface paths, event-day variance.

### 7.3 Forecast record and scoring

- **Record everything now, choose scoring later.** Each record stores the scenarios and weights, horizon, as-of date, forecaster and version, sticky rule, data version, and justification. With that stored, any scoring method can be applied to old forecasts.
- **Scoring:** calibration (does realized land in the 80% range 80% of the time), proper scoring rules, and comparison with naive benchmarks, above all implied vol used as the forecast.
- **Estimation windows:** rolling up to the last available day, configurable per forecaster.

### 7.4 The trader's view, as a modeling target

A worked example of the kind of view later forecasters should express: after a fall that bids call vol up relative to puts, the call-wing shock tends to partly unwind, and further declines lift those calls less than the first did. A trader sells calls with a delta hedge into that move and may roll them down into higher vol even at a loss. This is a conditional view of surface dynamics, measured against the static baseline, and history can quantify it (how much of a call-wing shock unwound over 1, 5 and 22 days, and how that changed when the index kept falling): the sentinel idea applied to points on the surface.

## 8. Phase 5 — Portfolio Construction & Walk-Forward (roadmap — not yet specified)

### 8.1 The research loop

1. **Forecast** (1a context, 1b forecast, 1c record).
2. **Construct** the target portfolio from the forecast and the user's constraints.
3. **Derive trades** from the difference between target and current.
4. **Step forward** a day; compute P&L and analytics.
5. **Repeat** over the window.
6. **Compute test statistics.**

Steps 1 and 2 run **every day**, because the data changes daily and implied vols and skew can move dramatically in a day.

**Walk-forward instead of holdout years.** At each date, use all data up to that date, decide, step forward a day, repeat, as in real trading. Every decision is then out of sample. What walk-forward does not protect is the choice of procedure: trying many procedure variants and keeping the best one is fit on the whole history, so the experiment ledger still counts procedure variants.

### 8.2 Constructors

All behind one interface (inputs: context, forecast, current book, policy and limits; output: orders and a justification):

- **Rules-based:** Phase 1's constructor.
- **Agent:** the LLM proposes trades through deterministic tools (get candidates, evaluate a proposed book, get book, submit to the risk gate). It never does arithmetic. Every decision is logged in full (briefing, tool calls, trades, justification) so a run can be replayed exactly without calling the model, distinct from re-deciding. A defined fallback applies when the agent fails (keep the book, keep hedging, log it). A per-day tool-call cap and a configurable model control cost.
- **Optimizer:** a linear program. Each contract is repriced independently per scenario, so expected P&L, per-scenario stress loss, trading costs (half-spread on what's traded), greek budgets and sizing caps are all linear in the quantities. A P&L-volatility limit makes it quadratic but still convex. cvxpy as the modeling layer.
- **Hybrid:** the agent narrows the choices and the optimizer sizes, or the optimizer proposes and the agent reviews.

### 8.3 Objective and constraints

- **Objective:** return per unit of stress loss. The ratio is independent of size, so the stress budget sets the size: maximize expected P&L net of costs with worst stress loss capped at the budget. *Pinned:* revisit if positions with little one-day slide risk make the agent or optimizer misbehave (multi-horizon stress is one fix).
- **Hedging is part of construction.** Once stress limits bind, buying options at negative expected value is worthwhile when it relaxes the limit enough to allow more of the profitable position. The limit has a price, and protection is bought until that price matches its cost. Even a one-opinion forecast produces relative-value structures because the surface has skew.
- **Margin:** portfolio margin is the assumed regime (no Reg T).
- **Configurable:** liquidity filters, tradable universe (per underlying), greek and tenor budgets (with the stress gate as the final check), forecast confidence, event rules.
- **Hold versus switch:** the current book is always valued under the new forecast and compared with the proposed book, net of costs.
- **Turnover:** costs inside the objective, a no-trade band (trade only when the improvement exceeds the cost), and a turnover cap as a backstop, so the book migrates rather than flips.
- **Own results:** the risk budget scales down with drawdown, subject to the opportunity in the forecast.

### 8.4 The daily pipeline

On each close: ingest and validate; mark the book and settle; update context; measure risk; fire mechanical rules (rolls, hedge bands, expiries) as required actions; screen opportunities; decide (constructor); pre-trade risk check with rejections returned; execute at the close with the hedge last; log the day.

The agent's briefing is a distilled packet, not the chain: what happened today (moves, P&L by structure with attribution, surface changes), where the book stands (positions, distance to triggers, greeks, stress matrix, limit usage), the market state with percentiles, required actions, screened opportunities with scenario P&L, and the calendar.

**One pipeline for live and historical use:** live, an LLM can sit in the decision step; in historical walk-forward, the deterministic policy takes that step, for cost and hindsight reasons. Everything around it is shared.

### 8.5 Process analytics

In addition to Phase 1's statistics: forecast accuracy, construction efficiency (how much of the forecast's value the portfolio captured) and execution cost, so a losing test can be traced to the forecast, the construction or the execution.

### 8.6 Reporting change

An optimized book is not made of named structures, so P&L is grouped by the date each position was opened and by tenor bucket.

## 9. Phase 6 — Research Agent & Scenario Tools (roadmap — not yet specified)

### 9.1 Scenario engine (realized-vs-implied grid)

For a position (for example a delta-hedged skew trade sold at 30 vol with a hedge bought at 15), simulate paths at chosen realized vols (10, 15, 20, 25, 30) through the same engine and report mean, spread and worst outcomes per realized level. The first-order relation is P&L ≈ Σ ½·Γ·S²·(σ_implied² − σ_realized²)·Δt, but out-of-the-money gamma moves with the index, so the answer depends on the path; this is why simulation is needed. Hedge-ratio vol (each leg's own implied vol, a common vol, or the realized forecast) is an explicit setting. Combined with the historical frequency of realized outcomes given today's state, it gives an expected P&L and tail estimate before a trade is placed. Useful to a trader directly, without any agent.

**Why it's needed even though the model "knows" the theory:** the model knows the gamma-theta tradeoff and the variance P&L formula, but cannot compute a specific position's path-dependent outcome on a real surface, cannot know facts about the user's data, and tends to produce plausible numbers when it cannot compute them. Its knowledge decides which question to ask and sanity-checks the answer (a short 30-vol position profiting at 40 realized is a bug).

### 9.2 Sentinel positions

A fixed set of six to ten reference trades (at-the-money straddle, 25-delta put and call, 25-delta risk reversal, put spread, calendar; each hedged and unhedged), run for every historical entry date, with outcomes stored and filtered at query time. They show what a price has historically been worth in similar states: evidence about edge that the surface alone does not contain. Requirements: conditioned on state, point-in-time (only trades already finished on the query date), and sample sizes reported with every number.

### 9.3 Regime analysis

Join a strategy's daily P&L to the market state on each position's entry day, group it (for example into terciles of the implied-minus-realized gap), and report average return, hit rate, worst outcomes, attribution split and trade counts per group. Built as a tool a person drives before an agent depends on it.

### 9.4 Experiment ledger and statistics

- An experiment holds a hypothesis written before anything runs, plus every run made under it; nothing is deleted; every refinement counts as more trials.
- Reports carry a Sharpe ratio deflated for the number of trials, confidence intervals, maximum drawdown, worst month and stress-episode results.
- Results that are compensation for tail risk (short vol paying steadily, then giving back in a crash) are labeled as such, distinct from possible edge; worst periods are always shown next to averages.
- Few real stress episodes exist in a 20-year daily history, so any claim about crisis behavior rests on a handful of observations and must say so.

### 9.5 Research agent

A second agent, separate from the chat assistant, with tools to create an experiment, run sweeps, run regime analysis, and write a findings report linked to every run behind it. Its output is a report, not a trading strategy.

### 9.6 Hindsight and memory

- The LLM sees everything up to the run date and nothing after, by construction of the data access.
- **The leak data controls can't remove:** the model's training includes text written after most historical dates, so on a run date in February 2020 it already knows a crash came in March. LLM decisions or forecasts on dates before the model's training cutoff are labeled *may contain hindsight*. Options considered: model-only historical runs, disguised data (dates removed, levels rescaled; this helps but doesn't eliminate the problem), restricting to periods after the training cutoff (clean but short).
- **Memory isolation:** if the agent gets memory, a run must not see anything learned in later runs, or in runs over later dates.

## 10. Trial Distribution (roadmap — not yet specified)

> **Not planned.** Phase 1 ships a standard pure Python wheel, with no compilation, obfuscation or license check (Phase 1 requirements v4, DIST-1), and nothing in Phase 1 is shaped around the options below. This section is kept as a record of the options discussed, should a protected trial ever be wanted.

**Goal:** give a prospective client the proof of concept as a wheel that stops working after a trial period (for example 14 or 30 days), without handing over readable source code. The hosted application remains the long-term answer to both problems; this is a short-term workaround.

**What is realistic.** Any check that runs on the client's machine can be defeated by a determined, skilled person, and so can any obfuscation. The aim is to make copying and extending the code expensive and clearly against the trial agreement, not impossible. A signed trial agreement that forbids reverse engineering is part of the protection, not an afterthought.

### 10.1 Expiry

Options, from simplest to strongest:

1. **Expiry baked into an obfuscated build.** PyArmor can generate obfuscated code that stops working after a number of days or on a date (`pyarmor gen -e 30 ...` or `-e 2026-12-31`), optionally checking an internet time server instead of the local clock, and optionally bound to one machine's hardware identifiers. One build per client, at the time of sending.
2. **A signed license file** (recommended). The application checks, at start-up, a small license file holding the client's name, an expiry date and optional limits, signed with a private key that stays with Chuck; the public key is inside the compiled code. One build serves every client; each client gets their own license file; extending a trial is a new file, not a new build. Detecting a clock set backwards (recording the latest time seen) closes the easiest workaround. Phase 1 has no license-check hook; one would be added with this work.
3. **Online activation** through a licensing service (for example Keygen or Cryptlex): the application checks in with a server. The strongest control (licenses can be revoked), but it needs a network connection and an account with a vendor.

"14 days of use" (counting days the program actually ran) needs locally stored state that a user can reset; "14 days from issue" (a calendar expiry date) is simpler and more robust, and is the suggested meaning.

### 10.2 Hiding the code

A wheel is a zip file, so plain `.py` files are readable. Options:

1. **Compile the core to native extension modules** (recommended) with **Cython** or **Nuitka** (module mode). The wheel then contains `.pyd` (Windows) or `.so` files instead of source; recovering logic means reverse-engineering machine code. Cost: a wheel per platform and Python version (a build matrix), and some dynamic Python features need care. The Phase 1 architecture makes the boundary natural: compile the pure engine, pricing, stress, selectors, conditions and statistics (DIST-2), and leave the FastAPI routes and pydantic models plain (DIST-3). Nuitka's commercial edition adds encryption of constants and data embedded in the compiled code.
2. **Obfuscate with PyArmor.** Works on the whole package and combines with its expiry and machine binding (§10.1, option 1). Real use needs a paid license (the trial version lacks advanced modes), adds some run-time overhead, and ties the build to specific Python versions.
3. **The front end** is already minified JavaScript in the built wheel; nothing further is needed there.

**Suggested combination:** Nuitka- or Cython-compiled core + a signed, expiring license file checked at start-up + a trial agreement. PyArmor is the single-tool alternative if one build per client is acceptable.

**Not protected by any of these:** what the program visibly does. A client can see every result, trade and statistic it produces; only the hosted model keeps the engine entirely out of reach.

## 11. Later — Hosted & Commercial (ideas)

- Multi-user hosting with authentication; a shared catalog (Postgres through the storage adapter); a real job queue.
- Remote market-data adapter if ivolatility (or another vendor) hosts a database for the client; not counted on for now.
- MCP server and directory listings for AI clients.
- More underlyings (NDX, RUT); equities, with corporate actions handled inside the data adapter so the engine always sees adjusted, consistent contracts.
- Hedging with futures or ETFs; financing and dividends.
- Economic-event data and event-day variance.
- Intraday data.

## 12. Decisions Log

Decisions made in discussion, by topic. Where a decision belongs to Phase 1, the Phase 1 specification is authoritative.

**Scope and approach**
- Build a single-user local application first, with a clean architecture for a remote database and hosting later.
- Phase 1 is deterministic only; AI is layered on afterwards and chooses what to test.
- No predetermined strategies: users describe structures; the engine knows only primitives.
- Start cheap; add complex pieces (such as a daily agent constructor) later; keep everything modular and configurable.

**Data**
- ivolatility daily closing data, with vendor IV and greeks.
- Indexes only at first (SPX); splits, dividends and symbol changes deferred.
- No preloaded vendor database assumed: users upload raw files, and everything is calculated from them.
- Uploads detect overlap by underlying and date range and ask whether to replace.
- A separate data module handles versioning and deletion.
- "Stock price for iv" is the vendor's per-series forward from Jun 25, 2018, and one price per date before; earlier forwards are derived from put-call parity on the strikes nearest the money, one per expiration (Phase 1 v6).
- The `*` flag's meaning is being confirmed; tracked, otherwise ignored.
- The vendor does not supply SET values; AM-settled contracts cannot be held to expiration.

**Engine and specs**
- Trades execute at the same close as the triggering observation (one could trade in the last hour in reality).
- At the money means 50 delta (or the forward), never nearest to spot; recorded in the conventions.
- Missing parameters are defaulted or asked for; whether and how to roll is a clarifying question, with re-establishing the whole structure as the default.
- Hedge rules are bands with a target; full hedging is the special case.
- Sizing by contracts or notional; capital is a configured input.
- Results at position level and portfolio level, with portfolio as the sum.
- **Snapshot nomenclature:** results are position, portfolio and stress snapshots taken at steps with an as-of timestamp, not "daily rows"; nothing assumes daily data except the frequency setting.
- **Time to expiry** is a year fraction computed from timestamps, matching the vendor's convention; selectors and conditions state their units (calendar days, trading days, nth expiration).
- P&L attribution by greek is wanted as a later add-on.
- **Profit and loss triggers are in dollars per structure unit,** not percentages: no denominator (entry premium, notional, stress loss) is well defined for every structure, notably ratios and near-zero-premium spreads (Phase 1 v3).
- **No guessed values at expiry:** an AM-settled leg with no valid quote on its last trading day closes at its last valid mark; a PM-settled leg whose expiration day is missing from the data closes at the step before. Closing early is preferred to inventing profit or loss (Phase 1 v3).
- The delta hedge is fractional (Phase 1 v3).
- **ProphetoVol has its own conventions** for time, prices, IV and greeks, independent of any vendor. Each data source has an adapter (its ingest) that converts into them and keeps the vendor's originals; the engine never depends on a vendor's conventions, so a new vendor means a new adapter, not engine changes. Greeks of the ivolatility single-price period (before Jun 25, 2018) are recomputed at ingest (Phase 1 v7).

**Stress**
- A stress module that builds stress grids and attaches them to runs; Phase 1 implements only the underlying slide; vol shocks and surface changes come later.
- Modes: **Monitor** (stress runs and reports but never interferes), **Scale to limit**, and **Halt run**. The AI will later choose the mode, so the modes are documented in the schema.

**Rule conditions**
- Left out of Phase 1: the user defines the structure and tests it. Conditions are pluggable so people can add them and an AI can define them later.

**Forecasting and construction (later phases)**
- Forecast contents: realized vol, surface moves, index distribution; as scenarios; horizons configurable with 22 trading days default and one day minimum; expressed relative to implied.
- Forecasters pluggable, with user override; LLM forecasts must justify themselves; start with the simplest.
- Static forecast first, with stubs for the rest; sticky strike configurable, one default; filtered historical simulation as the default index distribution, rescaled to the forecast realized vol.
- Steps 1 and 2 run daily.
- Objective: return per unit of stress loss (pinned for review).
- Portfolio margin assumed.
- Analytics are deterministic.
- Constructors pluggable; the rules-based constructor first; the agent constructor later.
- Walk-forward evaluation rather than holding out years.

**Platform**
- Same stack and design as the data profiling tool (FastAPI back end, Python computation, React front end). No shared libraries between the two projects: profiler code may be copied and adapted where that is quicker.
- Names: product ProphetoVol; package and CLI `prophetovol`; developed on Python 3.12.
- **Phase 1 is pure Python:** a standard wheel, with no compilation, obfuscation or license check (Phase 1 v4). A protected trial build (§10) is a possible later project, not planned.
- DuckDB now; designed to support other databases. Trino not needed.

## 13. Open Questions

| # | Question | Phase |
| --- | --- | --- |
| 1 | Meaning of the vendor `*` flag | 1 (tracked) |
| 2 | ~~Product, package and CLI names~~ **Resolved:** ProphetoVol; package and CLI `prophetovol` | 1 |
| 2a | Confirm the vendor's timing convention (16:15 ET snapshot; 16:00 and 09:30 ET expiries; calendar time over 365 days); also checked against real files in the implementation plan's Phase 0 | 1 |
| 3 | Default commission and fill model values | 1 |
| 4 | Order of Phases 2 and 3 (AI first, or market context first) | Planning |
| 5 | Should market-context snapshots be shown as a display before conditions use them? | 3 |
| 6 | Source and history depth of SET values (Cboe) | 3 |
| 7 | Default stress grids and loss limits for vol and joint scenarios | 3 |
| 8 | Default sticky rule for the static forecast (sticky strike proposed) | 4 |
| 9 | Surface parameterization, if and when synthetic surfaces are needed | 4 |
| 10 | Whether the objective needs multi-horizon stress in its denominator | 5 |
| 11 | How hindsight is handled for LLM decisions on historical dates | 5, 6 |
| 12 | Agent memory, and how it is isolated between runs | 6 |
| 13 | Trial mechanism: signed license file vs PyArmor per-client builds vs online activation; Cython vs Nuitka | Trial (not planned) |
| 14 | Trial length and meaning (14 or 30 days; calendar days from issue suggested) | Trial |

## 14. Lessons Carried Over from the Data Profiling Tool

Built in from the start of Phase 1 because the profiling tool found them late:

- software and library versions recorded on every run
- jobs persisted in the catalog, with cancellation
- deletion designed in, rather than an append-only assumption
- actor and channel on every action, and a log of rejected attempts
- one schema driving validation, the API, the GUI and documentation
- the OpenAPI document kept current by a test, with front-end types generated from it

## 15. Process

Following the profiling tool's process: backlog → requirements (agreed) → implementation plan (agreed) → implementation with tests → complete. Each phase here becomes one or more features in a backlog, with its own requirements specification and implementation plan. Requirement IDs are prefixed by area (as in the Phase 1 specification) so they can be referenced from plans, code and tests.

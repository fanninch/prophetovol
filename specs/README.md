# Specifications

This folder holds ProphetoVol's roadmap and every phase's requirements and implementation plan.

**Progress:** see the [Phase 1 requirement status](implementation_plans/ProphetoVol%20—%20Phase%201%20Requirement%20Status.md).

**What is being built:** Phase 1, exactly as defined by the agreed [Phase 1 requirements specification](requirements/ProphetoVol%20—%20Phase%201%20Requirements%20Specification.md) and its [implementation plan](implementation_plans/ProphetoVol%20—%20Phase%201%20Implementation%20Plan.md). The [roadmap](ProphetoVol%20—%20Project%20Roadmap.md) describes later phases for context only; nothing in it is built until it has its own agreed requirements and plan.

## How a phase is built

Each stage is reviewed and agreed before the next one starts.

1. **Roadmap.** Ideas for later phases are recorded in the [roadmap](ProphetoVol%20—%20Project%20Roadmap.md), with the reasoning behind them. Roadmap items are not specified and are not being built.
2. **Requirements.** When a phase (or a feature within one) is picked, its requirements specification is written in `requirements/` (*ProphetoVol — <Phase or feature> Requirements Specification*). It is reviewed and revised until agreed; its status line records the version and whether it is agreed, and each version lists what changed. Requirement IDs are prefixed by area (DATA-, SPEC-, ENG-, …) so plans, code and tests can refer to them.
3. **Implementation plan.** Once the requirements are agreed, an implementation plan is written in `implementation_plans/` (*ProphetoVol — <Phase or feature> Implementation Plan*): the design, a feasibility check (Phase 0), the phases with their tests, traceability to the requirements, decisions and risks. It is reviewed and agreed too.
4. **Implementation.** Phases are built one at a time, each with its tests, and the project README is updated. Each phase adds implementation notes to the plan (what was built, what changed from the plan, test counts), updates the plan's status line, and updates the **requirement status tracker** next to the plan (*ProphetoVol — <Phase> Requirement Status*): one row per requirement ID with its status (Done, Partial, Not started), the plan phase that did it, what remains, and its tests. The tracker is the place to see whether a requirement is done. Changes are left uncommitted: all git operations (branches, commits, pushes) are done by the project owner after review.
5. **Complete.** The status here and in the roadmap's phase summary is updated.

For Claude Code, `CLAUDE.md` at the repository root summarizes these rules, and the `phase-wrapup` skill (`.claude/skills/phase-wrapup/`) carries out step 4's documentation updates; `scripts/update_tracker.py` updates the requirement status tracker and checks it against the requirements.

If implementation shows that a requirement is wrong or incomplete, the requirements are revised as a new version and agreed before the code departs from them.

## Documents

| Phase | Requirements | Implementation plan | Status |
| --- | --- | --- | --- |
| [Roadmap](ProphetoVol%20—%20Project%20Roadmap.md) | | | Context for later phases; not being built |
| Phase 1: deterministic backtester | [Requirements](requirements/ProphetoVol%20—%20Phase%201%20Requirements%20Specification.md) (v7, agreed) | [Plan](implementation_plans/ProphetoVol%20—%20Phase%201%20Implementation%20Plan.md) (v4, agreed); [requirement status](implementation_plans/ProphetoVol%20—%20Phase%201%20Requirement%20Status.md) | Plan phases 0–8 of 24 done (M1 complete pending checkpoint 1); Phase 9 next |

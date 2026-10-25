# Specifications

This folder holds ProphetoVol's roadmap and every phase's requirements and implementation plan.

**What is being built:** Phase 1, exactly as defined by the agreed [Phase 1 requirements specification](requirements/ProphetoVol%20—%20Phase%201%20Requirements%20Specification.md) and its [implementation plan](implementation_plans/ProphetoVol%20—%20Phase%201%20Implementation%20Plan.md). The [roadmap](ProphetoVol%20—%20Project%20Roadmap.md) describes later phases for context only; nothing in it is built until it has its own agreed requirements and plan.

## How a phase is built

Each stage is reviewed and agreed before the next one starts.

1. **Roadmap.** Ideas for later phases are recorded in the [roadmap](ProphetoVol%20—%20Project%20Roadmap.md), with the reasoning behind them. Roadmap items are not specified and are not being built.
2. **Requirements.** When a phase (or a feature within one) is picked, its requirements specification is written in `requirements/` (*ProphetoVol — <Phase or feature> Requirements Specification*). It is reviewed and revised until agreed; its status line records the version and whether it is agreed, and each version lists what changed. Requirement IDs are prefixed by area (DATA-, SPEC-, ENG-, …) so plans, code and tests can refer to them.
3. **Implementation plan.** Once the requirements are agreed, an implementation plan is written in `implementation_plans/` (*ProphetoVol — <Phase or feature> Implementation Plan*): the design, a feasibility check (Phase 0), the phases with their tests, traceability to the requirements, decisions and risks. It is reviewed and agreed too.
4. **Implementation.** Phases are built one at a time, each with its tests, and the project README is updated. Each phase adds implementation notes to the plan (what was built, what changed from the plan, test counts) and updates the plan's status line. Changes are left uncommitted: all git operations (branches, commits, pushes) are done by the project owner after review.
5. **Complete.** The status here and in the roadmap's phase summary is updated.

If implementation shows that a requirement is wrong or incomplete, the requirements are revised as a new version and agreed before the code departs from them.

## Documents

| Phase | Requirements | Implementation plan | Status |
| --- | --- | --- | --- |
| [Roadmap](ProphetoVol%20—%20Project%20Roadmap.md) | | | Context for later phases; not being built |
| Phase 1: deterministic backtester | [Requirements](requirements/ProphetoVol%20—%20Phase%201%20Requirements%20Specification.md) (v3, agreed) | [Plan](implementation_plans/ProphetoVol%20—%20Phase%201%20Implementation%20Plan.md) | Plan in review |

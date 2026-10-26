---
name: phase-wrapup
description: Finish a portion of ProphetoVol work (a plan phase or a between-phase correction) - run the suites, update the plan's implementation notes and status line, the requirement status tracker and the status lines, then hand the owner a commit message. Use at the end of every portion, before saying it is ready to commit and tag.
---

# Finish a portion of work

ProphetoVol is built in portions: one plan phase each, or a correction between phases on its own
branch. Every portion ends with the steps below, in the same change as the code, so each commit
carries its own documentation. The project owner commits and tags; never run history-changing git
commands (they are denied in `.claude/settings.json`).

## 1. Suites green

```bash
.venv/Scripts/python.exe -m pytest -q
```

Everything must pass. Then count tests per folder for the notes:

```bash
for d in unit contract meta packaging; do printf "%s " $d; .venv/Scripts/python.exe -m pytest -q --collect-only tests/$d | grep -c "::"; done
```

If the editable install is stale (new package data, entry points or dependencies), reinstall first:

```bash
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-build-isolation --no-index -q -e ".[dev]"
```

## 2. Implementation notes and status in the plan

In `specs/implementation_plans/ProphetoVol — Phase 1 Implementation Plan.md`:

- Append a block to **§16 Implementation Notes**: `**Phase N (name), <date>**`, or for a correction
  `**<Name> change (between Phases N and N+1, branch <branch>), <date>**`. Cover: what was built (modules
  and their responsibilities), **what changed from the plan and why**, anything found and fixed while
  building, and the test count per folder.
- Update the **status line** (line 3): which plan phases are done and what is next.
- If a design decision was made, add it to **§13** (numbered, with "Added in vN" when the plan's
  version changed).

## 3. Requirement status tracker

Write a changes file in the scratchpad (not the repository) and apply it:

```json
{
  "through": "plan Phase N (name)",
  "phase_done": {"N": "<date>"},
  "m1": "**In progress:** phases 1–N done (<date>); … to go",
  "rows": {"DATA-13": {"status": "Done", "done_in": "N", "remaining": "", "tests": "`unit/test_x.py`"}},
  "add_rows": [{"after": "DATA-14", "id": "DATA-16", "summary": "…", "status": "Not started", "remaining": "Phase 7"}]
}
```

```bash
.venv/Scripts/python.exe scripts/update_tracker.py <changes.json>
```

Rules for rows:
- **Done** only when nothing is left to build for that requirement; otherwise **Partial** with what
  remains and in which plan phase.
- Cross-cutting rules (DOC-1, DOC-2, AUD-2, TIME-3, …) stay Partial while code keeps arriving.
- Name the tests that cover the row (paths under `tests/`).
- When the requirements gained IDs, add their rows; the script's coverage check must pass.

## 4. Status lines elsewhere

Keep these consistent with the plan's status line (plan phases done, what is next, document versions):
- `specs/README.md`: the Phase 1 row of the documents table
- `specs/ProphetoVol — Project Roadmap.md`: the Phase 1 row of the phase summary, and the decisions log
  for decisions that matter beyond Phase 1
- `README.md`: the status paragraph, and a section for any user-visible capability

Check for stale versions: `grep -rn "(v[0-9]*, agreed)" specs README.md` should show only current versions
(older ones only inside "Changes in vN" history).

## 5. Report to the owner

End with:
- **Ready to commit and tag**, and on which branch.
- A **commit message** in a fenced block: a title line (`Phase N: <name>` or the correction's name),
  then the pieces done, one bullet per module or document, citing requirement IDs; the test count; the
  tracker counts.
- Anything worth knowing: deviations from the plan, bugs found while building, and test mistakes found
  and fixed (say plainly that they were mistakes).
- What comes next.

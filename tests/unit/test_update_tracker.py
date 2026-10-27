"""The requirement status tracker updater (``scripts/update_tracker.py``)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("update_tracker", ROOT / "scripts" / "update_tracker.py")
tracker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tracker)

SAMPLE = """# Status

Oct 25, 2026 · **Up to date through plan Phase 5 (synthetic data generator).** · Tracks …

**4 requirements:** 1 done, 1 partial, 2 not started.

| Milestone | Plan phases | Status |
| --- | --- | --- |
| **M1 Data foundation** | 1–8 | **In progress:** phases 1–5 done |

| Plan phase | Content | Completed |
| --- | --- | --- |
| 5 | Synthetic data generator | Oct 25, 2026 |
| 6 | Ingest | — |

| Area | Done | Partial | Not started |
| --- | --- | --- | --- |
| Architecture (§4) | 1 | 1 | 0 |
| Data module (§6) | 0 | 0 | 2 |

## Architecture (§4)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| ARC-1 | One owner | **Done** | Phase 3 |  | `t.py` |
| ARC-2 | Pure engine | **Partial** | Phase 4 | rest (9) |  |

## Data module (§6)

| ID | Requirement | Status | Done in | Remaining or notes | Tests |
| --- | --- | --- | --- | --- | --- |
| DATA-1 | Format | Not started |  | Phase 6 |  |
| DATA-2 | Symbols | Not started |  | Phase 6 |  |
"""

SPEC = "\n".join(f"- **{rid}** text" for rid in ("ARC-1", "ARC-2", "DATA-1", "DATA-2"))


def test_changes_rows_and_recounts_everything():
    out = tracker.apply_changes(SAMPLE, {
        "through": "plan Phase 6 (ingest)",
        "phase_done": {"6": "Oct 26, 2026"},
        "m1": "**In progress:** phases 1–6 done",
        "rows": {"DATA-1": {"status": "Done", "done_in": "6", "remaining": "", "tests": "`unit/test_ingest.py`"},
                 "ARC-2": {"remaining": "rest (10)"}},
    })
    assert "| DATA-1 | Format | **Done** | Phase 6 |  | `unit/test_ingest.py` |" in out
    assert "| ARC-2 | Pure engine | **Partial** | Phase 4 | rest (10) |  |" in out
    assert "**4 requirements:** 2 done, 1 partial, 1 not started." in out
    assert "| Data module (§6) | 1 | 0 | 1 |" in out and "| Architecture (§4) | 1 | 1 | 0 |" in out
    assert "**Up to date through plan Phase 6 (ingest).**" in out
    assert "| 6 | Ingest | Oct 26, 2026 |" in out
    assert "| **M1 Data foundation** | 1–8 | **In progress:** phases 1–6 done |" in out
    assert tracker.summary(out) == {"total": 4, "Done": 2, "Partial": 1, "Not started": 1}


def test_sets_any_milestone_by_name():
    out = tracker.apply_changes(SAMPLE, {"milestones": {"M1 Data foundation": "**Done:** phases 1–8"}})
    assert "| **M1 Data foundation** | 1–8 | **Done:** phases 1–8 |" in out
    with pytest.raises(KeyError, match="milestone not found: M9"):
        tracker.apply_changes(SAMPLE, {"milestones": {"M9": "x"}})


def test_adds_rows_after_an_anchor():
    out = tracker.apply_changes(SAMPLE, {"add_rows": [{"after": "DATA-1", "id": "DATA-15", "summary": "Adapters",
                                                       "status": "Not started", "remaining": "Phase 6"}]})
    lines = out.split("\n")
    assert lines[lines.index(next(l for l in lines if l.startswith("| DATA-1 |"))) + 1].startswith("| DATA-15 | Adapters |")
    assert "**5 requirements:** 1 done, 1 partial, 3 not started." in out
    assert "| Data module (§6) | 0 | 0 | 3 |" in out


@pytest.mark.parametrize("changes, message", [
    ({"rows": {"NOPE-1": {"status": "Done"}}}, "rows not found"),
    ({"add_rows": [{"after": "NOPE-1", "id": "X-1", "summary": "x", "status": "Done"}]}, "anchor row not found"),
    ({"add_rows": [{"after": "ARC-1", "id": "ARC-2", "summary": "x", "status": "Done"}]}, "already exists"),
])
def test_mistakes_are_refused(changes, message):
    with pytest.raises(KeyError, match=message):
        tracker.apply_changes(SAMPLE, changes)


def test_coverage_against_the_specification():
    assert tracker.coverage(SAMPLE, SPEC) == (set(), set())
    missing, extra = tracker.coverage(SAMPLE, SPEC + "\n- **DATA-3** more")
    assert missing == {"DATA-3"} and extra == set()


def test_command_line(tmp_path, capsys):
    path, spec, changes = tmp_path / "t.md", tmp_path / "s.md", tmp_path / "c.json"
    path.write_text(SAMPLE, encoding="utf-8")
    spec.write_text(SPEC, encoding="utf-8")
    changes.write_text(json.dumps({"rows": {"DATA-2": {"status": "Partial", "done_in": "6"}}}), encoding="utf-8")
    assert tracker.main([str(changes), "--tracker", str(path), "--spec", str(spec)]) == 0
    assert "| DATA-2 | Symbols | **Partial** | Phase 6 |" in path.read_text(encoding="utf-8")
    spec.write_text(SPEC + "\n- **DATA-9** new", encoding="utf-8")
    assert tracker.main(["--check", "--tracker", str(path), "--spec", str(spec)]) == 1
    assert "missing ['DATA-9']" in capsys.readouterr().out


def test_the_real_tracker_covers_the_real_specification():
    text = tracker.TRACKER.read_text(encoding="utf-8")
    assert tracker.coverage(text, tracker.SPEC.read_text(encoding="utf-8")) == (set(), set())
    assert tracker.recount(text) == text  # the stored counts already match the rows

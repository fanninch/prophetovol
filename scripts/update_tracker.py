"""Update the requirement status tracker and recompute every count from its rows.

The tracker (``specs/implementation_plans/ProphetoVol — Phase 1 Requirement Status.md``) has one
table row per requirement ID::

    | ID | Requirement | Status | Done in | Remaining or notes | Tests |

This script changes rows from a JSON file of changes, then recomputes the summary line and the
per-area counts from the rows, so the totals can never drift from them. Optionally it checks that
the tracker has exactly the requirement IDs of the requirements specification.

Changes file (every key optional)::

    {
      "through": "plan Phase 6 (ingest)",                  # header: "Up to date through …"
      "phase_done": {"6": "Oct 26, 2026"},                 # fills the plan-phase table's date
      "m1": "**In progress:** phases 1–6 done; …",         # replaces the M1 milestone status
      "milestones": {"M2 Engine core": "**In progress:** …"},  # replaces any milestone's status by name
      "rows": {"DATA-13": {"status": "Done", "done_in": "6", "remaining": "", "tests": "`unit/…`"}},
      "add_rows": [{"after": "DATA-14", "id": "DATA-16", "summary": "…", "status": "Not started",
                    "done_in": "", "remaining": "Phase 7", "tests": ""}]
    }

``status`` is ``Done``, ``Partial`` or ``Not started``; ``done_in`` is written as ``Phase <value>``.

Usage::

    .venv/Scripts/python.exe scripts/update_tracker.py CHANGES.json [--tracker PATH] [--spec PATH]
    .venv/Scripts/python.exe scripts/update_tracker.py --check [--tracker PATH] [--spec PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "specs" / "implementation_plans" / "ProphetoVol — Phase 1 Requirement Status.md"
SPEC = ROOT / "specs" / "requirements" / "ProphetoVol — Phase 1 Requirements Specification.md"

ROW = re.compile(r"^\| ([A-Z]+-\d+) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$")
LABEL = {"Done": "**Done**", "Partial": "**Partial**", "Not started": "Not started"}


def _row(rid: str, summary: str, status: str, done_in: str, remaining: str, tests: str) -> str:
    """Format one tracker row.

    :param rid: The requirement ID.
    :param summary: The requirement's short summary.
    :param status: The status cell, already formatted.
    :param done_in: The "Done in" cell, already formatted.
    :param remaining: The "Remaining or notes" cell.
    :param tests: The tests cell.
    :returns: The table row.
    """
    return f"| {rid} | {summary} | {status} | {done_in} | {remaining} | {tests} |"


def _done_in(value: str) -> str:
    """Format a "Done in" cell.

    :param value: Plan phases, for example ``"6"`` or ``"2, 5"``; empty for none.
    :returns: ``Phase <value>``, or empty.
    """
    return f"Phase {value}" if value else ""


def apply_changes(text: str, changes: dict) -> str:
    """Apply row changes and additions, then recompute every count.

    :param text: The tracker's Markdown.
    :param changes: The changes (see the module description).
    :returns: The updated Markdown.
    :raises KeyError: If a changed or anchor row does not exist, or an added row already does.
    """
    lines = text.split("\n")
    pending = dict(changes.get("rows", {}))
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if not m or m.group(1) not in pending:
            continue
        rid, summary, status, done_in, remaining, tests = m.groups()
        ch = pending.pop(rid)
        lines[i] = _row(rid, ch.get("summary", summary), LABEL[ch["status"]] if "status" in ch else status,
                        _done_in(ch["done_in"]) if "done_in" in ch else done_in,
                        ch.get("remaining", remaining), ch.get("tests", tests))
    if pending:
        raise KeyError(f"rows not found: {sorted(pending)}")
    existing = {m.group(1) for line in lines if (m := ROW.match(line))}
    for add in changes.get("add_rows", []):
        if add["id"] in existing:
            raise KeyError(f"row already exists: {add['id']}")
        anchor = next((i for i, line in enumerate(lines) if line.startswith(f"| {add['after']} |")), None)
        if anchor is None:
            raise KeyError(f"anchor row not found: {add['after']}")
        lines.insert(anchor + 1, _row(add["id"], add["summary"], LABEL[add["status"]], _done_in(add.get("done_in", "")),
                                      add.get("remaining", ""), add.get("tests", "")))
        existing.add(add["id"])
    return recount("\n".join(lines), changes)


def recount(text: str, changes: dict | None = None) -> str:
    """Recompute the summary line and per-area counts, and apply header and table changes.

    :param text: The tracker's Markdown.
    :param changes: Optional ``through``, ``phase_done``, ``m1`` and ``milestones`` changes.
    :returns: The updated Markdown.
    """
    changes = changes or {}
    status_of = {m.group(1): m.group(3).strip("*") for line in text.split("\n") if (m := ROW.match(line))}
    counts = Counter(status_of.values())
    text = re.sub(r"\*\*\d+ requirements:\*\* \d+ done, \d+ partial, \d+ not started\.",
                  f"**{len(status_of)} requirements:** {counts['Done']} done, {counts['Partial']} partial, "
                  f"{counts['Not started']} not started.", text)
    # area headings ("## Data module (§6)") appear in the same order as the areas' rows
    titles = re.findall(r"^## (.+ \(§[\d.]+\))$", text, flags=re.M)
    prefixes = list(dict.fromkeys(rid.split("-")[0] for rid in status_of))
    for prefix, title in zip(prefixes, titles):
        c = Counter(s for rid, s in status_of.items() if rid.split("-")[0] == prefix)
        text = re.sub(rf"^\| {re.escape(title)} \| \d+ \| \d+ \| \d+ \|$",
                      f"| {title} | {c['Done']} | {c['Partial']} | {c['Not started']} |", text, flags=re.M)
    if "through" in changes:
        text = re.sub(r"\*\*Up to date through [^*]+\.\*\*", f"**Up to date through {changes['through']}.**", text)
    for phase, when in changes.get("phase_done", {}).items():
        text = re.sub(rf"^(\| {re.escape(phase)} \| [^|]+ \| )— \|$", rf"\g<1>{when} |", text, flags=re.M)
    if "m1" in changes:
        text = re.sub(r"^\| \*\*M1 Data foundation\*\* \| 1–8 \| .* \|$",
                      f"| **M1 Data foundation** | 1–8 | {changes['m1']} |", text, flags=re.M)
    for name, status in changes.get("milestones", {}).items():
        text, found = re.subn(rf"^(\| \*\*{re.escape(name)}\*\* \| [^|]+ \| ).* \|$",
                              lambda m: f"{m.group(1)}{status} |", text, flags=re.M)
        if not found:
            raise KeyError(f"milestone not found: {name}")
    return text


def summary(text: str) -> dict[str, int]:
    """Count the tracker's rows by status.

    :param text: The tracker's Markdown.
    :returns: Counts keyed ``total``, ``Done``, ``Partial`` and ``Not started``.
    """
    statuses = [m.group(3).strip("*") for line in text.split("\n") if (m := ROW.match(line))]
    c = Counter(statuses)
    return {"total": len(statuses), "Done": c["Done"], "Partial": c["Partial"], "Not started": c["Not started"]}


def coverage(tracker_text: str, spec_text: str) -> tuple[set[str], set[str]]:
    """Compare the tracker's requirement IDs with the specification's.

    :param tracker_text: The tracker's Markdown.
    :param spec_text: The requirements specification's Markdown.
    :returns: IDs in the specification but not the tracker, and IDs in the tracker but not the specification.
    """
    spec_ids = set(re.findall(r"^- \*\*([A-Z]+-\d+)\*\*", spec_text, flags=re.M))
    tracker_ids = {m.group(1) for line in tracker_text.split("\n") if (m := ROW.match(line))}
    return spec_ids - tracker_ids, tracker_ids - spec_ids


def main(argv: list[str] | None = None) -> int:
    """Run from the command line.

    :param argv: Arguments; ``sys.argv[1:]`` when omitted.
    :returns: The exit code: 0 on success, 1 if the tracker and specification disagree.
    """
    parser = argparse.ArgumentParser(description="Update the requirement status tracker and recount it.")
    parser.add_argument("changes", nargs="?", type=Path, help="JSON file of changes (omit with --check)")
    parser.add_argument("--tracker", type=Path, default=TRACKER, help="the tracker Markdown file")
    parser.add_argument("--spec", type=Path, default=SPEC, help="the requirements specification")
    parser.add_argument("--check", action="store_true", help="only check coverage and print the counts")
    args = parser.parse_args(argv)
    text = args.tracker.read_text(encoding="utf-8")
    if not args.check:
        if args.changes is None:
            parser.error("a changes file is required unless --check is given")
        text = apply_changes(text, json.loads(args.changes.read_text(encoding="utf-8")))
        args.tracker.write_text(text, encoding="utf-8", newline="\n")
    missing, extra = coverage(text, args.spec.read_text(encoding="utf-8"))
    print(summary(text))
    if missing or extra:
        print(f"tracker and specification disagree: missing {sorted(missing)}, extra {sorted(extra)}")
        return 1
    print("tracker covers every requirement ID in the specification")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Collecting a run's output in memory (plan §4.7, RUN-23).

The :class:`RunRecorder` keeps each table's rows as plain dicts with the fields of its record model
(:mod:`prophetovol.results.records`), appended per step, and turns them into Arrow tables for the
single write at the end of the run, whatever its outcome.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pyarrow as pa

from prophetovol.results.records import RECORD_MODELS, EventType, arrow_schema


class RunRecorder:
    """The output of one run, in memory until the run ends.

    :param run_id: The run's id, stamped on every row.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._rows: dict[str, list[dict[str, Any]]] = {name: [] for name in RECORD_MODELS if name != "structures"}
        self._structures: dict[str, dict[str, Any]] = {}

    def add(self, table: str, **fields: Any) -> None:
        """Append one row to a table (not ``structures``, which :meth:`set_structure` keeps).

        :param table: The table, for example ``position_snapshots``.
        :param fields: The row's fields, without ``run_id``.
        """
        self._rows[table].append({"run_id": self.run_id, **fields})

    def set_structure(self, structure_id: str, **fields: Any) -> None:
        """Record or update a structure's row; the last version is what the run stores.

        :param structure_id: The structure.
        :param fields: Its fields, without ``run_id`` and ``structure_id``.
        """
        self._structures[structure_id] = {"run_id": self.run_id, "structure_id": structure_id, **fields}

    def event(self, step: int, as_of: datetime, type: EventType, message: str, *, level: str = "info",
              structure_id: str | None = None, **details: Any) -> None:
        """Record an event (RES-20) with the next sequence number.

        :param step: The step.
        :param as_of: The step's as-of instant.
        :param type: What happened.
        :param message: For people.
        :param level: ``info`` or ``warning``.
        :param structure_id: The structure concerned, if any.
        :param details: Structured details.
        """
        self._rows["events"].append({"run_id": self.run_id, "seq": len(self._rows["events"]) + 1, "step": step,
                                     "as_of": as_of, "type": EventType(type).value, "level": level,
                                     "structure_id": structure_id, "message": message, "details": details})

    def keep_steps(self, steps: int) -> None:
        """Drop everything recorded after a step, so a stopped run keeps only its finished steps (RUN-22, RUN-23).

        Structures opened later are dropped; ones that closed later are shown open, as they were then.

        :param steps: The last finished step.
        """
        for table, rows in self._rows.items():
            self._rows[table] = [r for r in rows if r["step"] <= steps]
        for key, s in list(self._structures.items()):
            if s["opened_step"] > steps:
                del self._structures[key]
            elif s["closed_step"] is not None and s["closed_step"] > steps:
                self._structures[key] = s | {"closed_step": None, "closed_as_of": None, "status": "open"}

    def rows(self, table: str) -> list[dict[str, Any]]:
        """A table's rows so far.

        :param table: The table.
        :returns: The rows (dicts with the record model's fields), in the order recorded.
        """
        if table == "structures":
            return [self._structures[k] for k in self._structures]
        return self._rows[table]

    def tables(self) -> dict[str, pa.Table]:
        """Every table as Arrow, in its record model's schema; ``details`` become JSON text.

        :returns: Tables by name.
        """
        out = {}
        for name, model in RECORD_MODELS.items():
            rows = self.rows(name)
            if name == "events":
                rows = [r | {"details": json.dumps(r["details"], sort_keys=True, default=str)} for r in rows]
            out[name] = pa.Table.from_pylist(rows, schema=arrow_schema(model))
        return out

"""Identifiers, clock time and content hashes used by the service layer.

The engine never uses these: it reads no clock and creates no random ids (ENG-10).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def new_id(prefix: str) -> str:
    """A new random identifier such as ``imp_3f2a…``.

    :param prefix: A short kind marker: ``imp`` (import), ``job``, ``att`` (attempt), ``run``.
    :returns: The prefix, an underscore and 32 hexadecimal characters.
    """
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now() -> datetime:
    """The current time as an aware UTC datetime, to the microsecond.

    :returns: The current instant.
    """
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible data in one canonical form: sorted keys, no extra spaces.

    :param value: Data made of dicts, lists, strings, numbers, booleans and None.
    :returns: The canonical JSON text.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(value: Any) -> str:
    """The SHA-256 of the canonical JSON form (VER-2).

    :param value: JSON-compatible data.
    :returns: The hash as 64 hexadecimal characters.
    """
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

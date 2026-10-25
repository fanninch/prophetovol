"""Parameter models of the settlement sources (REF-20)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PmIndexCloseParams(BaseModel):
    """``pm_index_close`` takes no parameters: the settlement value is the index close on the settlement date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

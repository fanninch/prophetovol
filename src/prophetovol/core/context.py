"""Who is asking, and through which channel (AUD-1).

Every service operation that writes or can be refused receives a :class:`CallContext`.
"""

from __future__ import annotations

import getpass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Channel(StrEnum):
    """The client through which an operation was requested."""

    CLI = "cli"
    API = "api"
    GUI = "gui"
    LIBRARY = "library"


def current_actor() -> str:
    """Return the operating-system user running this process, the actor in Phase 1.

    :returns: The user name, or ``"unknown"`` if the operating system does not report one.
    """
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser raises various errors when no user is set
        return "unknown"


class CallContext(BaseModel):
    """The actor and channel recorded with every write and every attempt (AUD-1, AUD-2)."""

    model_config = ConfigDict(frozen=True)

    actor: str = Field(
        default_factory=current_actor,
        min_length=1,
        description="Who requested the operation. In Phase 1, the operating-system user.",
    )
    channel: Channel = Field(
        description="The client the request came through: cli, api, gui or library.",
    )

    @classmethod
    def for_channel(cls, channel: Channel | str) -> CallContext:
        """Build a context for the current operating-system user.

        :param channel: The channel the request came through.
        :returns: A context with the current user as actor.
        """
        return cls(channel=Channel(channel))

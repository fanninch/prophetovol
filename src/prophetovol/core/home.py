"""Where a ProphetoVol home directory is (ARC-7).

A home directory holds the catalog, the results and the market snapshots. It is chosen, in
order, by an explicit path (``--home``), the ``PROPHETOVOL_HOME`` environment variable, or the
default ``~/.prophetovol``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

HOME_ENV_VAR = "PROPHETOVOL_HOME"
"""Environment variable naming the home directory when no explicit path is given."""

DEFAULT_HOME_DIRNAME = ".prophetovol"
"""Name of the default home directory, inside the user's home folder."""


def resolve_home(explicit: str | os.PathLike[str] | None = None,
                 environ: Mapping[str, str] | None = None) -> Path:
    """Return the absolute path of the home directory to use. Nothing is created.

    :param explicit: A path given by the caller (for example ``--home``); wins when set.
    :param environ: The environment to read ``PROPHETOVOL_HOME`` from; defaults to ``os.environ``.
    :returns: The resolved absolute path, with ``~`` expanded.
    """
    env = os.environ if environ is None else environ
    if explicit is not None and str(explicit) != "":
        chosen = Path(explicit)
    elif env.get(HOME_ENV_VAR):
        chosen = Path(env[HOME_ENV_VAR])
    else:
        chosen = Path.home() / DEFAULT_HOME_DIRNAME
    return chosen.expanduser().resolve()

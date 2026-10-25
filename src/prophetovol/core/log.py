"""Logging set-up for the CLI and the server."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
"""Format of every log line."""


def configure_logging(level: int | str = logging.WARNING, log_file: Path | None = None) -> None:
    """Configure the ``prophetovol`` logger once per process.

    Messages go to standard error and, when ``log_file`` is given, also to that file (the
    server writes ``<home>/logs/server.log``). Calling it again replaces the handlers.

    :param level: The minimum level to emit, as a number or a name such as ``"INFO"``.
    :param log_file: Optional file to append log lines to; its folder is created if needed.
    """
    logger = logging.getLogger("prophetovol")
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(LOG_FORMAT)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    logger.propagate = False

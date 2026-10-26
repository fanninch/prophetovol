"""The attempts log: every requested operation and its outcome, including rejections (AUD-2).

Service operations are wrapped with :func:`audited`. Each call appends one attempt with the
operation's name, a summary of its parameters, the actor and channel from its ``context``
argument (AUD-1), and the outcome:

* ``ok`` when it returns;
* ``rejected`` when it raises a :class:`~prophetovol.core.errors.ProphetoVolError`, a deliberate
  refusal such as a validation error, a failed pre-flight or a refused delete, with the reasons;
* ``error`` for any other exception.

The exception is re-raised unchanged. Attempts are never deleted.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from prophetovol.core.context import CallContext
from prophetovol.core.errors import ProphetoVolError, ValidationFailed
from prophetovol.core.ids import new_id, utc_now
from prophetovol.core.records import AttemptOutcome, AttemptRecord

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_MAX_SUMMARY_TEXT = 200


def summarize_params(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep the simple parameters of a call for the attempts log.

    Strings (shortened to 200 characters), numbers, booleans and ``None`` are kept; for lists and
    dicts only their length is recorded; anything else is recorded by type name. ``self`` and
    ``context`` are left out.

    :param arguments: The call's arguments by name.
    :returns: The summary.
    """
    summary: dict[str, Any] = {}
    for name, value in arguments.items():
        if name in ("self", "context"):
            continue
        if value is None or isinstance(value, (bool, int, float)):
            summary[name] = value
        elif isinstance(value, str):
            summary[name] = value if len(value) <= _MAX_SUMMARY_TEXT else value[:_MAX_SUMMARY_TEXT] + "…"
        elif isinstance(value, (list, tuple, dict, set)):
            summary[name] = f"<{type(value).__name__} of {len(value)}>"
        else:
            summary[name] = f"<{type(value).__name__}>"
    return summary


def _reasons(exc: BaseException) -> list[str]:
    """The reasons recorded for a rejected or failed attempt.

    :param exc: The exception.
    :returns: One reason per validation issue, or the exception's message.
    """
    if isinstance(exc, ValidationFailed):
        return [str(issue) for issue in exc.issues]
    return [str(exc) or type(exc).__name__]


def audited(operation: str) -> Callable[[F], F]:
    """Record every call of a service method in the attempts log.

    The method must take a ``context: CallContext`` argument, and its object must have a
    ``storage`` attribute (a :class:`~prophetovol.storage.adapter.StorageAdapter`).

    :param operation: The operation's name in the log, for example ``reference.publish_underlying``.
    :returns: A decorator for the method.
    """
    def decorator(method: F) -> F:
        """Wrap ``method`` so each call appends an attempt.

        :param method: The service method.
        """
        signature = inspect.signature(method)
        if "context" not in signature.parameters:
            raise TypeError(f"{method.__qualname__} must take a 'context' argument to be audited")

        @functools.wraps(method)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Call the method and record the attempt.

            :param self: The service.
            :param args: Positional arguments of the method.
            :param kwargs: Keyword arguments of the method.
            """
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            context: CallContext = bound.arguments["context"]
            outcome, reasons = AttemptOutcome.OK, []
            try:
                return method(self, *args, **kwargs)
            except ProphetoVolError as exc:
                outcome, reasons = AttemptOutcome.REJECTED, _reasons(exc)
                raise
            except Exception as exc:
                outcome, reasons = AttemptOutcome.ERROR, _reasons(exc)
                raise
            finally:
                record = AttemptRecord(attempt_id=new_id("att"), operation=operation,
                                       params_summary=summarize_params(dict(bound.arguments)), outcome=outcome,
                                       reasons=reasons, actor=context.actor, channel=context.channel,
                                       attempted_at=utc_now())
                try:
                    self.storage.append_attempt(record)
                except Exception:  # noqa: BLE001 - never hide the operation's own result or error
                    log.exception("could not record attempt at %s", operation)

        return wrapper  # type: ignore[return-value]

    return decorator

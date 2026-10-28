"""Running a backtest as a job: from the recorded run to its stored results (RUN-20 to RUN-40).

A run is created by the service after pre-flight, with its provenance and the data versions it
will read (decision 30). Its job, :func:`execute_run`:

1. marks it ``running`` and rebuilds its step schedule from those versions;
2. runs the engine on the market data provider's views, reporting progress (RUN-21) and stopping at
   a step boundary when cancelled (RUN-22); Ctrl+C in the CLI counts as cancellation;
3. writes all of its output in one transaction, whatever the outcome (RUN-23): a cancelled run keeps
   its finished steps; a failed run keeps the steps before the failure, marked *partial*; if the
   write itself fails, nothing is stored and the run is ``failed``;
4. records the outcome on the run.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from prophetovol.core.errors import ProphetoVolError
from prophetovol.core.ids import utc_now
from prophetovol.core.records import RunRecord, RunStatus
from prophetovol.engine.book import BookSettings
from prophetovol.engine.fills import fill_model
from prophetovol.engine.loop import EngineSettings, run_engine
from prophetovol.reference.calendar import TradingCalendar
from prophetovol.reference.models import Underlying
from prophetovol.registry.catalog import get_registry
from prophetovol.results.recorder import RunRecorder
from prophetovol.runs.config import RunConfig
from prophetovol.runs.jobs import JobCancelled, JobContext
from prophetovol.runs.preflight import build_schedule
from prophetovol.runs.provider import MarketDataProvider, spec_horizon_days
from prophetovol.strategy.model import StrategySpec

Progress = Callable[[int, int, datetime], None]
"""Called after each step with steps done, steps in total and the step's as-of time."""


def registry_versions_used(spec: StrategySpec, config: RunConfig) -> dict[str, str]:
    """The implementation version of every registered component a run uses, keyed kind/name (REG-2, RUN-30).

    :param spec: The run's spec.
    :param config: The run's configuration.
    :returns: Versions by ``kind/name``.
    """
    used = {("constructor", "rules"), ("settlement_source", "pm_index_close"), ("fill_model", config.fill_model),
            ("entry_schedule", spec.entry.schedule), ("hedge_rule", spec.hedge.rule),
            ("sizing_method", spec.sizing.method)}
    for leg in spec.legs:
        used |= {("expiration_selector", leg.expiration.selector), ("strike_selector", leg.strike.selector)}
    for trigger in spec.triggers:
        used.add(("trigger_action", trigger.action))
        used |= {("trigger_condition", c.condition) for c in trigger.any_of}
    return {f"{kind}/{name}": get_registry(kind).get(name).version for kind, name in sorted(used)}


def engine_settings(config: RunConfig, underlying: Underlying) -> EngineSettings:
    """The engine's settings for a run (RUN-1, REF-1).

    :param config: The resolved configuration.
    :param underlying: The underlying's configuration.
    :returns: The settings.
    """
    book = BookSettings(multiplier=underlying.multiplier, capital=config.capital,
                        fill=fill_model(config.fill_model_params()),
                        commission_per_contract=config.commission_per_contract,
                        hedge_cost_bps=config.hedge_cost_bps,
                        stale_mark_warning_steps=config.stale_mark_warning_steps)
    return EngineSettings(book=book, rounding=config.rounding, timezone=underlying.timezone)


def execute_run(run: RunRecord, spec: StrategySpec, underlying: Underlying, calendar: TradingCalendar,
                ctx: JobContext, on_progress: Progress | None = None) -> dict[str, Any]:
    """Execute a run as its job (RUN-20 to RUN-23).

    :param run: The run, as created.
    :param spec: Its spec version.
    :param underlying: Its underlying configuration version.
    :param calendar: The trading calendar.
    :param ctx: The job's context: storage for this thread, progress and cancellation.
    :param on_progress: Also told of progress, for a foreground progress line.
    :returns: The job's result: the run's id and status.
    :raises JobCancelled: When the run was cancelled, after its results are stored.
    :raises Exception: The run's failure, after what it produced is stored.
    """
    storage = ctx.storage
    run = run.model_copy(update={"status": RunStatus.RUNNING, "started_at": utc_now(), "job_id": ctx.record.job_id})
    storage.update_run(run)
    config = RunConfig.model_validate(run.config)
    versions = storage.run_data_versions(run.run_id)
    by_day = {v.as_of_date: v for v in versions}
    schedule, versions = build_schedule(calendar.sessions_in_range(config.start_date, config.end_date), by_day)
    provider = MarketDataProvider(storage, run.underlying, schedule, versions, spec_horizon_days(spec))
    recorder = RunRecorder(run.run_id)
    done: list[Any] = [0, None]

    def progress(steps: int, total: int, as_of: datetime) -> None:
        """Record and report progress.

        :param steps: Steps done.
        :param total: Steps in total.
        :param as_of: The step's as-of time.
        """
        done[:] = [steps, as_of]
        ctx.progress(steps, total, f"step {steps} of {total}, as of {as_of:%Y-%m-%d}")
        if on_progress is not None:
            on_progress(steps, total, as_of)

    status, error, partial, failure = RunStatus.COMPLETED, None, False, None
    try:
        outcome = run_engine(spec, engine_settings(config, underlying), schedule, provider.views(), calendar, recorder,
                             progress=progress, cancelled=lambda: ctx.cancelled)
        status = RunStatus.COMPLETED if outcome.status == "completed" else RunStatus.CANCELLED
    except KeyboardInterrupt:
        status, error = RunStatus.CANCELLED, "cancelled by the user"
    except Exception as exc:  # noqa: BLE001 - the failure is recorded on the run and re-raised for the job
        status, error, partial, failure = RunStatus.FAILED, str(exc) or type(exc).__name__, True, exc
    recorder.keep_steps(done[0])
    try:
        storage.write_run_results(run.run_id, recorder.tables())
        stored = True
    except Exception as exc:  # noqa: BLE001 - RUN-23: nothing is stored and the run fails
        status, partial, failure, stored = RunStatus.FAILED, False, exc, False
        error = f"results could not be stored: {exc}"
    last = recorder.rows("portfolio_snapshots")[-1] if stored and recorder.rows("portfolio_snapshots") else None
    run = run.model_copy(update={
        "status": status, "error": error, "partial": partial, "steps_completed": done[0], "last_as_of": done[1],
        "final_pnl": last["cumulative_pnl"] if last else None, "final_equity": last["equity"] if last else None,
        "finished_at": utc_now()})
    storage.update_run(run)
    if status is RunStatus.CANCELLED:
        raise JobCancelled()
    if failure is not None:
        if isinstance(failure, ProphetoVolError):
            raise failure
        raise RuntimeError(f"run {run.run_id} failed: {error}") from failure
    return {"run_id": run.run_id, "status": status.value}

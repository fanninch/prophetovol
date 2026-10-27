"""The rows a run produces (RES-1, RES-2, RES-10, RES-11, RES-20).

Each model documents one stored table's columns (DOC-1). The engine's
:class:`~prophetovol.results.recorder.RunRecorder` collects rows with exactly these fields, and
:func:`arrow_schema` gives the matching Arrow schema for the single write at the end of the run
(RUN-23). Money is in dollars, prices in index points per unit of the underlying, greeks in the
internal conventions (CONV-10), and positive cash flow is cash received (CONV-8).
"""

from __future__ import annotations

import types
import typing
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field


class MarkSource(StrEnum):
    """Where a position's mark at a step came from (RES-1, ENG-21, ENG-22)."""

    MID = "mid"
    STALE = "stale"
    FILL = "fill"
    SETTLEMENT = "settlement"
    INDEX = "index"


class EventType(StrEnum):
    """What a run event records (RES-20)."""

    ENTRY = "entry"
    ENTRY_SKIPPED = "entry_skipped"
    TRIGGER_FIRED = "trigger_fired"
    ROLL = "roll"
    CLOSE = "close"
    SETTLEMENT = "settlement"
    FORCED_CLOSE_AM = "forced_close_am"
    FORCED_CLOSE_MISSING_EXPIRY = "forced_close_missing_expiry"
    HEDGE_TRADE = "hedge_trade"
    STRESS_SCALED = "stress_scaled"
    STRESS_SKIPPED = "stress_skipped"
    STRESS_HALTED = "stress_halted"
    STRESS_WOULD_HAVE_ACTED = "stress_would_have_acted"
    STRESS_BREACH = "stress_breach"
    SELECTION_FAILED = "selection_failed"
    STALE_MARK = "stale_mark"
    ORDER_NOT_FILLED = "order_not_filled"
    CONDITION_NULL_GREEK = "condition_null_greek"


_RUN = "The run's id."
_STEP = "The step's number, from 1."
_AS_OF = "The step's as-of instant (UTC)."


class PositionSnapshot(BaseModel):
    """One security held or traded at a step, including the step it closes or settles at (RES-1, RES-2).

    The hedge of a structure is the security ``hedge``: a synthetic index position whose price is the index
    level, with multiplier 1 and no option fields.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description=_RUN)
    step: int = Field(description=_STEP)
    as_of: datetime = Field(description=_AS_OF)
    structure_id: str = Field(description="The structure the security belongs to, for example S3.")
    leg_id: str = Field(description="The spec leg it fills, or hedge for the structure's index hedge.")
    position_key: str = Field(description="The position's id within the run: structure, leg (or hedge) and contract.")
    osi_symbol: str | None = Field(description="The contract's OSI symbol, its identity with the underlying "
                                               "(DATA-2); null for the hedge.")
    root: str | None = Field(description="The normalized root, SPX or SPXW; null for the hedge.")
    vendor_symbol: str | None = Field(description="The vendor's option symbol, kept for tracing, never an identifier.")
    vendor_root: str | None = Field(description="The vendor's option root.")
    settlement_style: str | None = Field(description="AM or PM; null for the hedge.")
    expiration: date | None = Field(description="The expiration date as listed.")
    settlement_date: date | None = Field(description="The settlement date (CONV-3).")
    last_trading_date: date | None = Field(description="The last trading day (CONV-3).")
    expiry_timestamp: datetime | None = Field(description="The expiry instant (UTC).")
    strike: float | None = Field(description="The strike; null for the hedge.")
    option_type: str | None = Field(description="call or put; null for the hedge.")
    quantity: float = Field(description="Signed quantity after the step's trades: contracts for options, index units "
                                        "for the hedge; positive is long (CONV-8). 0 at the step it closes or settles.")
    time_to_expiry_years: float | None = Field(description="Time to expiry in years on the exchange clock (CONV-1).")
    days_to_expiry: float | None = Field(description="Time to expiry in fractional calendar days (CONV-1).")
    trading_days_to_expiry: int | None = Field(description="Trading days to expiry (CONV-2).")
    mark: float | None = Field(description="Price per unit used for the market value: the mid of a valid quote, the last "
                                           "valid mark when stale, the fill or settlement price at the closing step, "
                                           "or the index level for the hedge.")
    mark_source: MarkSource = Field(description="mid, stale, fill, settlement or index (ENG-21, ENG-22).")
    bid: float | None = Field(description="The snapshot's bid; null when the contract is absent from it.")
    ask: float | None = Field(description="The snapshot's ask; null when the contract is absent from it.")
    iv: float | None = Field(description="The snapshot's implied vol as a decimal (CONV-10).")
    index_level: float = Field(description="The index level of the step's snapshot.")
    forward: float | None = Field(description="The series forward (DATA-14).")
    forward_source: str | None = Field(description="vendor, parity or vendor_single_price (DATA-14).")
    market_value: float = Field(description="quantity · mark · multiplier, in dollars (ENG-30).")
    cash_flow: float = Field(description="The step's cash flows in dollars: trades (−Δq · price · multiplier − fees) "
                                         "and settlement (q · value · multiplier); positive is cash received.")
    fees: float = Field(description="Commissions and hedge costs paid at the step, in dollars, as a positive number; "
                                    "already included in cash_flow and the P&L (ENG-31).")
    period_pnl: float = Field(description="market_value − previous market_value + cash_flow, in dollars (ENG-30).")
    cumulative_pnl: float = Field(description="The position's P&L since it opened, in dollars.")
    delta: float | None = Field(description="The snapshot's delta per contract (CONV-10); 1 for the hedge.")
    gamma: float | None = Field(description="The snapshot's gamma per contract (CONV-10).")
    vega: float | None = Field(description="The snapshot's vega per contract, per volatility point (CONV-10).")
    theta: float | None = Field(description="The snapshot's theta per contract, per calendar day (CONV-10).")
    dollar_delta: float | None = Field(description="delta · quantity · multiplier · index level (CONV-7); for the "
                                                   "hedge, quantity · index level (RES-2).")
    dollar_gamma_1pct: float | None = Field(description="gamma · quantity · multiplier · index level² · 0.01: the change "
                                                        "in dollar delta for a 1% index move (CONV-7); 0 for the hedge.")
    dollar_vega: float | None = Field(description="vega · quantity · multiplier, per volatility point (CONV-7); 0 for "
                                                  "the hedge.")
    dollar_theta: float | None = Field(description="theta · quantity · multiplier, per calendar day (CONV-7); 0 for "
                                                   "the hedge.")
    flags: list[str] = Field(description="Data and handling flags, for example stale_mark, forced_close_stale, "
                                         "vendor_flagged, missing_day_before.")


class PortfolioSnapshot(BaseModel):
    """The whole run's totals at a step (RES-10)."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description=_RUN)
    step: int = Field(description=_STEP)
    as_of: datetime = Field(description=_AS_OF)
    index_level: float = Field(description="The index level of the step's snapshot.")
    market_value: float = Field(description="Sum of the step's position market values, in dollars.")
    cash_flow: float = Field(description="Sum of the step's position cash flows, in dollars.")
    fees: float = Field(description="Sum of the step's fees, in dollars.")
    period_pnl: float = Field(description="Sum of the step's position period P&L, in dollars.")
    cumulative_pnl: float = Field(description="The run's P&L from its start to this step, in dollars.")
    equity: float = Field(description="capital + cumulative_pnl, in dollars (ENG-32).")
    period_return: float = Field(description="period_pnl / capital: the step's return on the run's capital.")
    dollar_delta: float = Field(description="Sum of the positions' dollar deltas (null ones count as 0).")
    dollar_gamma_1pct: float = Field(description="Sum of the positions' dollar gammas for a 1% move.")
    dollar_vega: float = Field(description="Sum of the positions' dollar vegas.")
    dollar_theta: float = Field(description="Sum of the positions' dollar thetas.")
    open_structures: int = Field(description="Structures open after the step's trades.")
    contracts_held: float = Field(description="Option contracts held after the step's trades, in absolute terms.")
    worst_stress_loss: float | None = Field(description="The worst stress loss across attached definitions, in dollars; "
                                                        "null until stress arrives (M3) or with none attached.")
    flags: list[str] = Field(description="Step flags, for example missing_day_before.")


class TradeRecord(BaseModel):
    """One fill: an option leg or a hedge, opening or closing (§5.2 Trade)."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description=_RUN)
    trade_id: str = Field(description="The trade's id within the run, for example T12.")
    step: int = Field(description=_STEP)
    as_of: datetime = Field(description=_AS_OF)
    structure_id: str = Field(description="The structure traded.")
    leg_id: str = Field(description="The leg, or hedge.")
    position_key: str = Field(description="The position traded.")
    osi_symbol: str | None = Field(description="The contract; null for the hedge.")
    action: Literal["open", "close", "adjust"] = Field(description="open or close for options; adjust for hedge trades.")
    quantity: float = Field(description="Signed quantity traded: positive bought, negative sold.")
    price: float = Field(description="Fill price per unit: from the fill model, the last valid mark for a stale forced "
                                     "close, or the index level for the hedge.")
    fees: float = Field(description="Commission or hedge cost paid, in dollars, as a positive number.")
    cash_flow: float = Field(description="−quantity · price · multiplier − fees, in dollars.")
    reason: str = Field(description="Why: entry, roll, a trigger's name, forced_close_am, "
                                    "forced_close_missing_expiry, expiry_handling, close or hedge.")
    forced: bool = Field(description="Whether it was a forced close (SPEC-51, SPEC-55).")


class StructureRecord(BaseModel):
    """One structure opened during a run, as it ended (§5.2 Structure)."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description=_RUN)
    structure_id: str = Field(description="The structure's id within the run, for example S3.")
    parent_id: str | None = Field(description="The structure it replaced in a structure roll (SPEC-43).")
    units: float = Field(description="Structure units N; leg i holds N · ratio_i contracts (SPEC-70).")
    opened_step: int = Field(description="The step it opened at.")
    opened_as_of: datetime = Field(description="When it opened (UTC).")
    closed_step: int | None = Field(description="The step it finished closing at; null if still open at the end.")
    closed_as_of: datetime | None = Field(description="When it finished closing (UTC).")
    status: Literal["open", "closing", "closed"] = Field(description="open, closing (a close waits for a valid quote) "
                                                                     "or closed, at the end of the run.")
    cumulative_pnl: float = Field(description="Its P&L from opening, legs, hedge and fees together (SPEC-46), in dollars.")


class RunEvent(BaseModel):
    """Something that happened in a run (RES-20)."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description=_RUN)
    seq: int = Field(description="The event's sequence number in the run, from 1.")
    step: int = Field(description=_STEP)
    as_of: datetime = Field(description=_AS_OF)
    type: EventType = Field(description="What happened (RES-20).")
    level: Literal["info", "warning"] = Field(description="warning for data issues and handling that deserve attention.")
    structure_id: str | None = Field(description="The structure concerned, where there is one.")
    message: str = Field(description="What happened, for people.")
    details: dict[str, Any] = Field(description="Structured details: legs, contracts, prices, conditions, reasons.")


RECORD_MODELS: dict[str, type[BaseModel]] = {
    "position_snapshots": PositionSnapshot, "portfolio_snapshots": PortfolioSnapshot, "trades": TradeRecord,
    "structures": StructureRecord, "events": RunEvent}
"""The run output tables and the model of each one's rows."""


def _arrow_type(annotation: Any) -> pa.DataType:
    """The Arrow type of a record field.

    :param annotation: The field's annotation.
    :returns: The type; dicts are stored as JSON text.
    """
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return _arrow_type(args[0])
    if typing.get_origin(annotation) is list:
        return pa.list_(_arrow_type(args[0]))
    if typing.get_origin(annotation) in (dict, Literal) or annotation is dict:
        return pa.string()
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return pa.string()
    return {bool: pa.bool_(), int: pa.int64(), float: pa.float64(), str: pa.string(), date: pa.date32(),
            datetime: pa.timestamp("us", tz="UTC")}[annotation]


def arrow_schema(model: type[BaseModel]) -> pa.Schema:
    """The Arrow schema of a record model's table, in field order.

    :param model: One of :data:`RECORD_MODELS`.
    :returns: The schema.
    """
    hints = typing.get_type_hints(model)
    return pa.schema([(name, _arrow_type(hints[name])) for name in model.model_fields])

"""The changes of a step: its ledger, its events and the numbers of an identifier.

Examples:
    >>> identifier_numbers("transfer-3-10")
    (3, 10)
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.models.state import EventValue, LedgerRow, State

ZERO_QUANTITY = Decimal("0.000")


def identifier_numbers(identifier: str) -> tuple[int, int]:
    """Give the period and the position of an identifier.

    An identifier reads `<prefix>-<period>-<position>` or `<period>-<position>`.

    Args:
        identifier (str): The identifier.

    Returns:
        tuple[int, int]: The period and the position.

    Examples:
        >>> identifier_numbers("make-12-2"), identifier_numbers("3-10")
        ((12, 2), (3, 10))
    """
    period, position = identifier.split("-")[-2:]
    return int(period), int(position)


def add_events(state: State, events: Sequence[Mapping[str, EventValue]]) -> State:
    """Add events to the `events` and the `period_events` of a state.

    Args:
        state (State): The state.
        events (Sequence[Mapping[str, str | int | Decimal | tuple[str, ...]]]): The new
            events, in the order they happened.

    Returns:
        State: The state with the events.

    Examples:
        >>> state = State(
        ...     period=1, cash=Decimal(0), stock={}, condition={}, customer_orders=()
        ... )
        >>> state = add_events(state, [{"kind": "breakdown", "reference": "press"}])
        >>> state.period_events[0]["kind"]
        'breakdown'
    """
    new_events = tuple(MappingProxyType(dict(event)) for event in events)
    return replace(
        state,
        events=(*state.events, *new_events),
        period_events=(*state.period_events, *new_events),
    )


@dataclass(slots=True)
class Ledger:
    """The movements of cash of a period, booked by one step one after another.

    Attributes:
        period (int): The period.
        step (str): The name of the step.
        cash (Decimal): Cash after the last movement.
        rows (list[LedgerRow]): Every movement of the period so far.
        events (list[dict[str, str | int | Decimal | tuple[str, ...]]]): The events of
            this step.

    Examples:
        >>> ledger = Ledger(
        ...     period=1, step="execute_decisions", cash=Decimal(100), rows=[]
        ... )
        >>> ledger.book("production_cost", Decimal(-30), "make-1-1")
        >>> ledger.cash
        Decimal('70')
    """

    period: int
    step: str
    cash: Decimal
    rows: list[LedgerRow]
    events: list[dict[str, EventValue]] = field(
        default_factory=list[dict[str, EventValue]]
    )

    def book(
        self,
        kind: str,
        amount: Decimal,
        reference: str,
        event_kind: str | None = None,
        fields: Mapping[str, EventValue] = MappingProxyType({}),
    ) -> None:
        """Book cash by an amount, adding its row and its event; 0 adds nothing.

        Args:
            kind (str): The kind of movement.
            amount (Decimal): The amount, positive when cash rises.
            reference (str): The identifier the movement belongs to.
            event_kind (str | None, optional): The kind of its event; None for a
                movement without an event.
            fields (Mapping[str, str | int | Decimal | tuple[str, ...]], optional): The
                other fields of its event, none when not given.

        Examples:
            >>> ledger = Ledger(
            ...     period=1, step="execute_decisions", cash=Decimal(100), rows=[]
            ... )
            >>> ledger.book("repair_cost", Decimal(-25), "repair-1-1")
            >>> ledger.rows[0].cash_after
            Decimal('75')
        """
        if amount == 0:
            return
        if event_kind is not None:
            self.add_event(event_kind, reference, fields)
        self.cash += amount
        row = LedgerRow(
            period=self.period,
            step=self.step,
            kind=kind,
            amount=amount,
            cash_after=self.cash,
            reference=reference,
        )
        self.rows.append(row)

    def add_event(
        self, kind: str, reference: str, fields: Mapping[str, EventValue]
    ) -> None:
        """Add an event of this step.

        Args:
            kind (str): The kind of the event.
            reference (str): The identifier the event concerns.
            fields (Mapping[str, str | int | Decimal | tuple[str, ...]]): Its
                other fields.

        Examples:
            >>> ledger = Ledger(period=1, step="close_period", cash=Decimal(0), rows=[])
            >>> ledger.add_event("breakdown", "press", {"loss": Decimal("0.1")})
            >>> ledger.events[0]["step"]
            'close_period'
        """
        event: dict[str, EventValue] = {
            "kind": kind,
            "step": self.step,
            "reference": reference,
        }
        self.events.append(event | dict(fields))

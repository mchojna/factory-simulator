"""The mapped classes of runs: a run and every table that belongs to it.

Examples:
    >>> Run.__tablename__
    'runs'
"""

from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factory_simulator.api.record.models.base import DECIMAL, Base
from factory_simulator.api.record.models.scenario import Scenario


class Period(Base):
    """A closed period of a run.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        observation (object): The observation of the period.
        submission (object): The validated submission.
        state (object): The public state at the close.
        private (object): The private state at the close.

    Examples:
        >>> Period(run_id="r-1", period=1).period
        1
    """

    __tablename__ = "periods"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation: Mapped[object] = mapped_column(JSON)
    submission: Mapped[object] = mapped_column(JSON)
    state: Mapped[object] = mapped_column(JSON)
    private: Mapped[object] = mapped_column(JSON)


class Trace(Base):
    """A private transition of a closed period.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        position (int): The order of the transition in the period, from 1.
        step (str): The step of the period.
        kind (str): The kind of the step or the decision.
        reference (str): The identifier of the period, the decision or the scheduled
            plan.
        decision_id (str | None): The identifier of the decision, absent for steps.
        input (object): The normalized input.
        outcome (object): The outcome of the decision, absent for steps.
        before (object): The complete values before the transition.
        after (object): The complete values after the transition.

    Examples:
        >>> Trace(run_id="r-1", period=1, position=1).position
        1
    """

    __tablename__ = "traces"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    step: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    reference: Mapped[str] = mapped_column(String)
    decision_id: Mapped[str | None] = mapped_column(String)
    input: Mapped[object] = mapped_column(JSON(none_as_null=True), nullable=True)
    outcome: Mapped[object] = mapped_column(JSON(none_as_null=True), nullable=True)
    before: Mapped[object] = mapped_column(JSON)
    after: Mapped[object] = mapped_column(JSON)


class Event(Base):
    """An event of a period.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        position (int): The order of the event in the period, from 1.
        step (str): The step that reported it.
        kind (str): The kind of event.
        reference (str): The identifier it concerns.
        fields (object): Its other fields.

    Examples:
        >>> Event(run_id="r-1", period=1, position=1, kind="breakdown").kind
        'breakdown'
    """

    __tablename__ = "events"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    step: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    reference: Mapped[str] = mapped_column(String)
    fields: Mapped[object] = mapped_column(JSON)


class LedgerEntry(Base):
    """A movement of cash: one row of the ledger.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        position (int): The order of the movement in the period, from 1.
        step (str): The step that booked it.
        kind (str): The kind of movement.
        amount (Decimal): The amount, positive when cash rises.
        cash_after (Decimal): Cash after the movement.
        reference (str): The identifier the movement belongs to.

    Examples:
        >>> LedgerEntry(run_id="r-1", period=1, amount=Decimal("-120.5")).amount
        Decimal('-120.5')
    """

    __tablename__ = "ledger"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    step: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    amount: Mapped[Decimal] = mapped_column(DECIMAL)
    cash_after: Mapped[Decimal] = mapped_column(DECIMAL)
    reference: Mapped[str] = mapped_column(String)


class Outcome(Base):
    """What happened to one decision.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        position (int): The order of the decision in the period, from 1.
        decision_id (str): The identifier of the decision.
        kind (str): The kind of the decision.
        accepted (bool): Whether it was executed.
        reason (str | None): Why it was rejected.
        outcome (object): The whole outcome.

    Examples:
        >>> Outcome(run_id="r-1", period=1, accepted=True).accepted
        True
    """

    __tablename__ = "outcomes"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String)
    outcome: Mapped[object] = mapped_column(JSON)


class Measure(Base):
    """The value of a measure in a period.

    Attributes:
        run_id (str): The identifier of the run.
        period (int): The period.
        name (str): The name of the measure.
        key (str): The object it is measured for.
        value (Decimal | None): The value.

    Examples:
        >>> Measure(run_id="r-1", period=1, name="cash", key="total").key
        'total'
    """

    __tablename__ = "measures"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(DECIMAL)


class World(Base):
    """Every value of a run drawn from its seed.

    Attributes:
        run_id (str): The identifier of the run.
        world (object): The world in the shape of the record.

    Examples:
        >>> World(run_id="r-1", world={}).world
        {}
    """

    __tablename__ = "worlds"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    world: Mapped[object] = mapped_column(JSON)


class Result(Base):
    """The result of a finished run.

    Attributes:
        run_id (str): The identifier of the run.
        profit (Decimal): Profit.
        cash_at_start (Decimal): Cash before period 1.
        cash_at_end (Decimal): Cash after the last period.
        receivables (Decimal | None): Money customers still owe.
        terms (object): Each term of profit.
        measures (object): The measures of the whole run.

    Examples:
        >>> Result(run_id="r-1", profit=Decimal("12.5")).profit
        Decimal('12.5')
    """

    __tablename__ = "results"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    profit: Mapped[Decimal] = mapped_column(DECIMAL)
    cash_at_start: Mapped[Decimal] = mapped_column(DECIMAL)
    cash_at_end: Mapped[Decimal] = mapped_column(DECIMAL)
    receivables: Mapped[Decimal | None] = mapped_column(DECIMAL)
    terms: Mapped[object] = mapped_column(JSON)
    measures: Mapped[object] = mapped_column(JSON)


class Interaction(Base):
    """A check or a refused submission, kept apart from the run.

    Attributes:
        run_id (str): The identifier of the run.
        position (int): The order of the interaction in the run, from 1.
        period (int): The current period of the run.
        kind (str): `check` or `refusal`.
        submission (object): The submission as received.
        outcomes (object | None): The outcomes of a check.
        refusal (str | None): Why a submission was refused.

    Examples:
        >>> Interaction(run_id="r-1", position=1, period=1, kind="check").kind
        'check'
    """

    __tablename__ = "interactions"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    submission: Mapped[object] = mapped_column(JSON)
    outcomes: Mapped[object | None] = mapped_column(JSON(none_as_null=True))
    refusal: Mapped[str | None] = mapped_column(String)


class Run(Base):
    """A run of a scenario with a seed, and the versions it ran with.

    Attributes:
        id (str): 32 hexadecimal digits.
        scenario_id (str): The identifier of its scenario.
        seed (str): The seed as canonical decimal text.
        period (int): The current period, or the last one once finished.
        finished (bool): Whether the last period is closed.
        description (object): What the agent is told before period 1.
        package_version (str): The version of the package.
        numpy_version (str): The version of numpy.
        python_version (str): The version of Python.
        pydantic_version (str): The version of pydantic.
        duckdb_version (str): The version of DuckDB.
        platform (str): `sys.platform`.
        forked_from (str | None): The run it was forked from.
        forked_from_period (int | None): The period it was forked at.
        scenario (Scenario): Its scenario.
        world (World | None): Its world.
        result (Result | None): Its result once finished.

    Examples:
        >>> Run(id="r-1", seed="7", period=1, finished=False).seed
        '7'
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"))
    seed: Mapped[str] = mapped_column(String)
    period: Mapped[int] = mapped_column(Integer)
    finished: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[object] = mapped_column(JSON)
    package_version: Mapped[str] = mapped_column(String)
    numpy_version: Mapped[str] = mapped_column(String)
    python_version: Mapped[str] = mapped_column(String)
    pydantic_version: Mapped[str] = mapped_column(String)
    duckdb_version: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    forked_from: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    forked_from_period: Mapped[int | None] = mapped_column(Integer)

    scenario: Mapped[Scenario] = relationship()
    world: Mapped[World | None] = relationship()
    result: Mapped[Result | None] = relationship()

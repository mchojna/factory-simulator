"""The reader of a submission: the decisions of the engine, with defaults of the run.

Examples:
    >>> repair = {"kind": "repair", "line": "smt", "amount": "0.2"}
    >>> body = {"period": 1, "decisions": [repair]}
    >>> to_decisions(DecisionsCreate.model_validate(body)).decisions[0].kind
    'repair'
"""

from factory_simulator import engine
from factory_simulator.api.schemas.run import (
    BuyCreate,
    CancelCreate,
    DecisionCreate,
    DecisionsCreate,
    ProduceCreate,
    RepairCreate,
    ShipCreate,
    TransferCreate,
)


def with_defaults(model: DecisionsCreate, factory: engine.Factory) -> DecisionsCreate:
    """Give a submission with the defaults of every decision that depend on the run.

    A produce left without `start` starts in the period of the submission; one left
    without `recipe` takes the default recipe of its item, when the item exists. A
    ship or buy left without `warehouse` takes the only warehouse of the manifest.

    Args:
        model (DecisionsCreate): The validated submission.
        factory (Factory): The factory of the run.

    Returns:
        DecisionsCreate: The submission with each default it can fill.

    Raises:
        InputError: If a ship or buy leaves out `warehouse` while the manifest has
            several warehouses.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes, validate
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.readers.manifest import read_factory
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> factory = read_factory(content)
        >>> produce = {
        ...     "kind": "produce",
        ...     "line": "smt-line",
        ...     "item": "control-board",
        ...     "quantity": "10",
        ... }
        >>> submission = {"period": 2, "decisions": [produce]}
        >>> model = validate(DecisionsCreate, submission)
        >>> filled = with_defaults(model, factory).decisions[0]
        >>> filled.start, filled.recipe
        (2, 'standard')
    """
    decisions: list[DecisionCreate] = []
    for position, decision in enumerate(model.decisions):
        if isinstance(decision, ShipCreate | BuyCreate) and decision.warehouse is None:
            if len(factory.warehouses) > 1:
                raise engine.InputError(
                    f"decisions.{position}.warehouse: Field required"
                )
            only = next(iter(factory.warehouses))
            decision = decision.model_copy(update={"warehouse": only})
        if isinstance(decision, ProduceCreate):
            filled: dict[str, object] = {}
            if decision.start is None:
                filled["start"] = model.period
            made = factory.components.get(decision.item) or factory.products.get(
                decision.item
            )
            if decision.recipe is None and made is not None:
                filled["recipe"] = made.default_recipe
            decision = decision.model_copy(update=filled)
        decisions.append(decision)
    return model.model_copy(update={"decisions": tuple(decisions)})


def to_decisions(model: DecisionsCreate) -> engine.Decisions:
    """Convert a submission of decisions.

    Args:
        model (DecisionsCreate): The validated submission.

    Returns:
        Decisions: The decisions for the engine.

    Examples:
        >>> body = {
        ...     "period": 1,
        ...     "decisions": [{"kind": "ship", "order": "order-1-1", "quantity": "5"}],
        ... }
        >>> to_decisions(DecisionsCreate.model_validate(body)).period
        1
    """
    return engine.Decisions(
        period=model.period,
        decisions=tuple(to_decision(decision) for decision in model.decisions),
    )


def to_decision(model: DecisionCreate) -> engine.Decision:
    """Convert one decision.

    Args:
        model (DecisionCreate): The validated decision.

    Returns:
        Decision: The decision for the engine.

    Examples:
        >>> ship = ShipCreate(kind="ship", order="order-1-1", quantity="5")
        >>> to_decision(ship)
        Ship(kind='ship', order='order-1-1', quantity=Decimal('5.000'), warehouse=None)
    """
    if isinstance(model, ShipCreate):
        return engine.Ship(
            kind=model.kind,
            order=model.order,
            quantity=model.quantity,
            warehouse=model.warehouse,
        )
    if isinstance(model, ProduceCreate):
        return engine.Produce(
            kind=model.kind,
            line=model.line,
            item=model.item,
            quantity=model.quantity,
            recipe=model.recipe,
            overtime=model.overtime,
            start=model.start,
        )
    if isinstance(model, RepairCreate):
        return engine.Repair(kind=model.kind, line=model.line, amount=model.amount)
    if isinstance(model, CancelCreate):
        return engine.Cancel(
            kind=model.kind, order=model.order, quantity=model.quantity
        )
    if isinstance(model, TransferCreate):
        return engine.Transfer(
            kind=model.kind,
            item=model.item,
            quantity=model.quantity,
            source=model.source,
            destination=model.destination,
        )
    return engine.Buy(
        kind=model.kind,
        supplier=model.supplier,
        material=model.material,
        quantity=model.quantity,
        express=model.express,
        warehouse=model.warehouse,
    )

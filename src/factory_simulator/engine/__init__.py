"""The engine: the rules of the factory on frozen dataclasses.

It reads and writes nothing; the HTTP interface gives it its inputs.

Examples:
    >>> from decimal import Decimal
    >>> forecast_quantity(Decimal("50.000"), Decimal("-0.0800"))
    Decimal('46.000')
"""

from factory_simulator.engine.checks.linear import is_linear
from factory_simulator.engine.checks.manifest import check_factory
from factory_simulator.engine.checks.scenario import check_scenario
from factory_simulator.engine.description import build_description
from factory_simulator.engine.draws.forecasts import (
    draw_forecast_increment,
    forecast_quantity,
)
from factory_simulator.engine.draws.streams import open_stream
from factory_simulator.engine.draws.values import (
    carry_demand_over,
    choose_target,
    combine_demand_draws,
    draw_value,
    is_within_chance,
    raised_chances,
    range_mean,
)
from factory_simulator.engine.draws.world import draw_world
from factory_simulator.engine.economics import (
    CustomerProductProfile,
    EconomicProfile,
    build_economic_profile,
)
from factory_simulator.engine.generation import generate_manifest
from factory_simulator.engine.measures.kinds import MEASURE_KINDS
from factory_simulator.engine.models.decisions import (
    Buy,
    Cancel,
    Decision,
    Decisions,
    Produce,
    Repair,
    Ship,
    Transfer,
)
from factory_simulator.engine.models.manifest import (
    Cash,
    CatalogueEntry,
    Customer,
    CustomerProduct,
    DiscountTier,
    Factory,
    Group,
    Line,
    LineItem,
    MadeItem,
    Material,
    Product,
    Range,
    Route,
    Supplier,
    Warehouse,
)
from factory_simulator.engine.models.scenario import (
    Cascade,
    DemandShape,
    Disruption,
    Forecast,
    Ramp,
    RandomDisruption,
    Scenario,
    SCurve,
    Season,
    Start,
    StartCustomerOrder,
    StartSupplierOrder,
    Step,
    Trend,
)
from factory_simulator.engine.models.state import (
    CustomerOrder,
    Event,
    ForecastSeen,
    LedgerRow,
    LineHours,
    Observation,
    Outcome,
    Plan,
    Production,
    ProductionSeen,
    Receivable,
    State,
    SupplierOrder,
    SupplierOrderSeen,
    Tallies,
    TransferOnTheWay,
    WarehouseSpace,
)
from factory_simulator.engine.models.world import (
    Breakdown,
    Delivery,
    Description,
    World,
)
from factory_simulator.engine.money import (
    compute_interest,
    compute_profit,
    compute_salvage,
)
from factory_simulator.engine.numbers import CONTEXT, InputError, in_decimal_context
from factory_simulator.engine.rules.demand import demand_factor
from factory_simulator.engine.rules.disruptions import is_active, is_visible
from factory_simulator.engine.rules.targets import targets_of
from factory_simulator.engine.steps.period import (
    advance_period,
    build_outcomes,
    build_state,
    start_period,
)

__all__ = [
    "CONTEXT",
    "MEASURE_KINDS",
    "Breakdown",
    "Buy",
    "Cancel",
    "Cascade",
    "Cash",
    "CatalogueEntry",
    "Customer",
    "CustomerOrder",
    "CustomerProduct",
    "CustomerProductProfile",
    "Decision",
    "Decisions",
    "Delivery",
    "DemandShape",
    "Description",
    "DiscountTier",
    "Disruption",
    "EconomicProfile",
    "Event",
    "Factory",
    "Forecast",
    "ForecastSeen",
    "Group",
    "InputError",
    "LedgerRow",
    "Line",
    "LineHours",
    "LineItem",
    "MadeItem",
    "Material",
    "Observation",
    "Outcome",
    "Plan",
    "Produce",
    "Product",
    "Production",
    "ProductionSeen",
    "Ramp",
    "RandomDisruption",
    "Range",
    "Receivable",
    "Repair",
    "Route",
    "SCurve",
    "Scenario",
    "Season",
    "Ship",
    "Start",
    "StartCustomerOrder",
    "StartSupplierOrder",
    "State",
    "Step",
    "Supplier",
    "SupplierOrder",
    "SupplierOrderSeen",
    "Tallies",
    "Transfer",
    "TransferOnTheWay",
    "Trend",
    "Warehouse",
    "WarehouseSpace",
    "World",
    "advance_period",
    "build_description",
    "build_economic_profile",
    "build_outcomes",
    "build_state",
    "carry_demand_over",
    "check_factory",
    "check_scenario",
    "choose_target",
    "combine_demand_draws",
    "compute_interest",
    "compute_profit",
    "compute_salvage",
    "demand_factor",
    "draw_forecast_increment",
    "draw_value",
    "draw_world",
    "forecast_quantity",
    "generate_manifest",
    "in_decimal_context",
    "is_active",
    "is_linear",
    "is_visible",
    "is_within_chance",
    "open_stream",
    "raised_chances",
    "range_mean",
    "start_period",
    "targets_of",
]

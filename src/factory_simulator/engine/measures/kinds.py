"""The kinds of the measures: flows, levels and ratios.

Examples:
    >>> MEASURE_KINDS["cash"], MEASURE_KINDS["revenue"]
    ('level', 'flow')
"""

from collections.abc import Mapping
from types import MappingProxyType

# The flows measured under the total, each customer, product and customer product.
CUSTOMER_FLOWS = (
    "revenue",
    "late_penalty",
    "lost_sale_penalty",
    "units_ordered",
    "units_shipped",
    "units_shipped_on_time",
    "units_shipped_late",
    "units_lost",
    "units_past_due",
    "units_past_due_on_time",
)

# The ledger kinds measured as a positive number under the total only.
COST_KINDS = (
    "material_payment",
    "repair_cost",
    "production_cost",
    "interest_paid",
    "interest_earned",
)

# The ledger kinds measured under the total and under the warehouse.
WAREHOUSE_COST_KINDS = ("transport_cost", "storage_cost")

# The flows measured under each line.
LINE_FLOWS = (
    "hours_available",
    "regular_hours",
    "overtime_hours",
    "repair_hours",
    "changeover_hours",
    "changeovers",
    "breakdowns",
)

# The flows measured under each line and under each line with its item.
LINE_ITEM_FLOWS = ("units_started", "units_good", "units_scrap")

# The flows measured under each supplier with its material.
SUPPLIER_FLOWS = (
    "units_ordered_from_suppliers",
    "units_arrived",
    "units_accepted",
    "units_rejected_at_inspection",
    "units_lost_in_delivery",
    "units_cancelled",
    "units_arrived_late",
)

# The counts of decisions and plans under the total; rejections also under each reason.
DECISION_FLOWS = (
    "decisions_accepted",
    "decisions_rejected",
    "plans_made",
    "plans_run",
    "plans_rejected",
    "plans_cancelled",
)

# The running sums kept only for a ratio.
LATE_UNIT_PERIODS = "late_unit_periods"
ORDERS_CLOSED = "orders_closed"
ORDERS_IN_FULL_ON_TIME = "orders_in_full_on_time"
CAPACITY = "capacity"
REGULAR_AND_CHANGEOVER_HOURS = "regular_and_changeover_hours"

# The ratios: the name of each, the running sum above the line and the one below.
RATIOS = (
    ("service", "units_past_due_on_time", "units_past_due"),
    ("on_time_share", "units_shipped_on_time", "units_shipped"),
    ("orders_in_full_on_time_share", ORDERS_IN_FULL_ON_TIME, ORDERS_CLOSED),
    ("mean_lateness", LATE_UNIT_PERIODS, "units_shipped_late"),
    ("utilisation", REGULAR_AND_CHANGEOVER_HOURS, CAPACITY),
)

# The kind of every measure the engine computes.
MEASURE_KINDS: Mapping[str, str] = MappingProxyType(
    {
        **dict.fromkeys(CUSTOMER_FLOWS, "flow"),
        **dict.fromkeys(COST_KINDS, "flow"),
        **dict.fromkeys(WAREHOUSE_COST_KINDS, "flow"),
        **dict.fromkeys(LINE_FLOWS, "flow"),
        **dict.fromkeys(LINE_ITEM_FLOWS, "flow"),
        **dict.fromkeys(SUPPLIER_FLOWS, "flow"),
        "cancellation_fee": "flow",
        "overtime_cost": "flow",
        "changeover_cost": "flow",
        "units_transferred": "flow",
        "units_used": "flow",
        "transfer_cost": "flow",
        "periods_below_credit_limit": "flow",
        **dict.fromkeys(DECISION_FLOWS, "flow"),
        "cash": "level",
        "profit_so_far": "level",
        "receivables": "level",
        "stock": "level",
        "stock_salvage_value": "level",
        "stock_space": "level",
        "space_used": "level",
        "condition": "level",
        **{name: "ratio" for name, _, _ in RATIOS},
    }
)

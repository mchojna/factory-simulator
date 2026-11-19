from factory_simulator.engine import MEASURE_KINDS

# The kind of every measure of the engine, one row per line of the table of measures.
KINDS_OF_THE_TABLE = {
    "revenue": "flow",
    "material_payment": "flow",
    "transport_cost": "flow",
    "repair_cost": "flow",
    "production_cost": "flow",
    "storage_cost": "flow",
    "interest_paid": "flow",
    "interest_earned": "flow",
    "cancellation_fee": "flow",
    "overtime_cost": "flow",
    "changeover_cost": "flow",
    "transfer_cost": "flow",
    "late_penalty": "flow",
    "lost_sale_penalty": "flow",
    "cash": "level",
    "profit_so_far": "level",
    "receivables": "level",
    "periods_below_credit_limit": "flow",
    "units_ordered": "flow",
    "units_shipped": "flow",
    "units_shipped_on_time": "flow",
    "units_shipped_late": "flow",
    "units_lost": "flow",
    "units_past_due": "flow",
    "units_past_due_on_time": "flow",
    "service": "ratio",
    "on_time_share": "ratio",
    "orders_in_full_on_time_share": "ratio",
    "mean_lateness": "ratio",
    "stock": "level",
    "stock_salvage_value": "level",
    "stock_space": "level",
    "units_used": "flow",
    "space_used": "level",
    "units_transferred": "flow",
    "units_started": "flow",
    "units_good": "flow",
    "units_scrap": "flow",
    "regular_hours": "flow",
    "overtime_hours": "flow",
    "repair_hours": "flow",
    "changeover_hours": "flow",
    "changeovers": "flow",
    "breakdowns": "flow",
    "condition": "level",
    "hours_available": "flow",
    "utilisation": "ratio",
    "plans_made": "flow",
    "plans_run": "flow",
    "plans_rejected": "flow",
    "plans_cancelled": "flow",
    "units_ordered_from_suppliers": "flow",
    "units_arrived": "flow",
    "units_accepted": "flow",
    "units_rejected_at_inspection": "flow",
    "units_lost_in_delivery": "flow",
    "units_cancelled": "flow",
    "units_arrived_late": "flow",
    "decisions_accepted": "flow",
    "decisions_rejected": "flow",
}


def test_every_measure_of_the_engine_has_the_kind_of_its_row_of_the_table():
    assert dict(MEASURE_KINDS) == KINDS_OF_THE_TABLE


def test_the_running_sums_of_ratios_and_the_size_of_an_observation_are_not_measures():
    kept_for_ratios = {
        "late_unit_periods",
        "orders_closed",
        "orders_in_full_on_time",
        "capacity",
        "regular_and_changeover_hours",
    }

    assert not kept_for_ratios & set(MEASURE_KINDS)
    assert "observation_size" not in MEASURE_KINDS

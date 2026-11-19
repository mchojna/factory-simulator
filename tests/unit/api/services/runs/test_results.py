from decimal import Decimal

from factory_simulator.api.services.runs.results import run_measures


def test_the_flows_of_a_run_are_summed_with_every_digit():
    revenue = Decimal("12345678901234567.123456789012")

    measures = run_measures([("revenue", "total", revenue)] * 2)

    assert measures["total"] == {"revenue": Decimal("24691357802469134.246913578024")}

from collections.abc import Callable
from decimal import Decimal

from factories import plain_tiny_description, plain_tiny_observation

from factory_simulator.benchmark.client import Check
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer
from factory_simulator.benchmark.program.decisions import Optimizer


# The terminal value of one unit of every item in period 1 of a horizon of 10.
def terminal_values(make_optimizer: Callable[[Check], Optimizer]) -> dict[str, Decimal]:
    observation = plain_tiny_observation() | {"horizon": 10}
    optimizer = make_optimizer(lambda period, decisions: [])
    planning = optimizer.planning_source(plain_tiny_description(), observation)
    return {item_id: value.value for item_id, value in planning.terminal_values.items()}


# The replacement costs of the plain tiny factory are chip 0.5, board 2 and monitor 6:
# 1.2 times them for the buffered rolling optimizer, 1.01 times for the rolling one.
def test_the_buffered_rolling_optimizer_values_stock_at_1_2_and_the_rolling_at_1_01():
    assert terminal_values(buffered_rolling_optimizer) == {
        "chip": Decimal("0.6"),
        "board": Decimal("2.4"),
        "monitor": Decimal("7.2"),
    }
    assert terminal_values(rolling_optimizer) == {
        "chip": Decimal("0.505"),
        "board": Decimal("2.02"),
        "monitor": Decimal("6.06"),
    }

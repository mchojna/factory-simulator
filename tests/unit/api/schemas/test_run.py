import pytest

from factory_simulator.api.core.numbers import validate
from factory_simulator.api.schemas.run import DecisionsCreate
from factory_simulator.engine import InputError


def test_a_produce_error_path_holds_no_tag_of_the_kind():
    produce = {"kind": "produce", "line": "line-1", "item": "board"}
    body = {"period": 1, "decisions": [produce | {"quantity": "1.0001"}]}

    with pytest.raises(InputError, match=r"^decisions\.0\.quantity: "):
        validate(DecisionsCreate, body)


def test_a_produce_refuses_a_warehouse():
    produce = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "1"}
    body = {"period": 1, "decisions": [produce | {"warehouse": "main"}]}

    with pytest.raises(InputError, match=r"^decisions\.0\.warehouse: "):
        validate(DecisionsCreate, body)


@pytest.mark.parametrize("amount", ["0.0000", "0.00001"])
def test_a_repair_amount_must_be_above_0_with_at_most_4_places(amount: str):
    repair = {"kind": "repair", "line": "line-1", "amount": amount}

    with pytest.raises(InputError, match=r"^decisions\.0\.amount: "):
        validate(DecisionsCreate, {"period": 1, "decisions": [repair]})

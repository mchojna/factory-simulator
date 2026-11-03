import typing

from pydantic import BaseModel

from factory_simulator.api.schemas import manifest
from factory_simulator.engine.rules.parameters import MONEY_KEYS


def test_the_money_keys_are_the_keys_the_http_interface_reads_as_amounts_of_money():
    money_keys = {
        key
        for model in vars(manifest).values()
        if isinstance(model, type) and issubclass(model, BaseModel)
        for key, hint in typing.get_type_hints(model, include_extras=True).items()
        if manifest.MoneyParameter in (hint, *typing.get_args(hint))
    }

    assert money_keys == MONEY_KEYS
    assert len(MONEY_KEYS) == 12

from factory_simulator.engine.changes import identifier_numbers


def test_an_identifier_gives_its_period_and_position():
    assert identifier_numbers("transfer-3-10") == (3, 10)
    assert identifier_numbers("make-12-2") == (12, 2)
    assert identifier_numbers("3-10") == (3, 10)

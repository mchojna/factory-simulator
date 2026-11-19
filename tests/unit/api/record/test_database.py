import uuid
from decimal import Decimal, localcontext
from typing import cast

import pytest
from factories import example_count
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import QueuePool, select
from sqlalchemy.orm import Session

from factory_simulator.api.core.json import decimal_text, write_json
from factory_simulator.api.record.database import (
    canonical_text,
    create_database_engine,
    prepare,
    read_column,
    recorded_value,
)
from factory_simulator.api.record.models.base import SchemaVersion
from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.models.run import LedgerEntry, Measure, Run
from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.api.record.repositories.runs import insert_rows
from factory_simulator.engine import InputError

decimals_of_the_record = st.decimals(
    min_value=-(10**26) + 1,
    max_value=10**26 - 1,
    places=12,
    allow_nan=False,
    allow_infinity=False,
)


json_values = st.recursive(
    st.one_of(decimals_of_the_record, st.integers(), st.text(), st.booleans()),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(max_size=5), children, max_size=3),
    ),
    max_leaves=10,
)


def floats_in(value: object) -> list[object]:
    if isinstance(value, dict):
        items = list(cast(dict[str, object], value).values())
    elif isinstance(value, list):
        items = cast(list[object], value)
    else:
        return [value] if isinstance(value, float) else []
    return [found for item in items for found in floats_in(item)]


def add_run(session: Session) -> None:
    session.add(Manifest(id="m", content={}, linear=True))
    session.add(Scenario(id="s", manifest_id="m", content={}))
    session.add(
        Run(
            id="r",
            scenario_id="s",
            seed="7",
            period=1,
            finished=False,
            description={},
            package_version="1.2.3",
            numpy_version="2.5.3",
            python_version="3.14.0",
            pydantic_version="2.13.5",
            duckdb_version="1.5.6",
            platform="darwin",
        )
    )
    session.flush()


def test_a_decimal_with_13_places_is_refused():
    with pytest.raises(ValueError, match=r"^ledger\.amount: more than 12 places$"):
        recorded_value("ledger.amount", Decimal("0.0000000000001"))


def test_places_are_counted_after_trailing_zeros_are_removed():
    recorded_value("ledger.amount", Decimal("1.5000000000000"))


def test_a_decimal_with_13_places_inside_json_is_refused():
    observation = {"stock": {"main": [Decimal(1), Decimal("0.1234567890123")]}}

    with pytest.raises(
        ValueError, match=r"^periods\.observation: more than 12 places$"
    ):
        recorded_value("periods.observation", observation)


def test_a_13th_place_of_a_24_digit_number_is_refused_at_any_precision():
    with (
        localcontext(prec=28),
        pytest.raises(ValueError, match=r"^ledger\.amount: more than 12 places$"),
    ):
        recorded_value(
            "ledger.amount", Decimal("123456789012345678901234.0000000000001")
        )


def test_a_number_of_27_digits_before_the_point_is_refused():
    with pytest.raises(
        ValueError, match=r"^ledger\.amount: more than 26 digits before the point$"
    ):
        recorded_value("ledger.amount", Decimal("1" + "0" * 26))


def test_a_json_decimal_the_record_cannot_read_back_is_refused_as_the_reader_does():
    state = {"cash": Decimal("1E+50")}

    with pytest.raises(InputError) as reading:
        read_column(canonical_text(state))
    with pytest.raises(ValueError) as writing:
        recorded_value("periods.state", state)

    assert str(reading.value) == "cash: has more than 50 digits"
    assert str(writing.value) == "periods.state: has more than 50 digits"


def test_a_json_decimal_of_50_whole_digits_is_kept_and_read_back():
    state = {"cash": Decimal("9" * 50)}

    recorded_value("periods.state", state)

    assert read_column(canonical_text(state)) == state


def test_a_request_waits_30_seconds_for_a_free_connection_of_a_named_database():
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")

    timeout = cast(QueuePool, database.pool).timeout()
    database.dispose()
    assert timeout == 30


def test_a_new_database_gets_one_row_of_its_version():
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")

    prepare(database, "1.2.3")
    prepare(database, "1.2.3")

    with Session(database) as session:
        versions = session.scalars(select(SchemaVersion.version)).all()
    database.dispose()
    assert versions == ["1.2.3"]


def test_measures_inserted_with_the_rows_of_a_period_keep_every_digit():
    values = [
        Decimal("12345678901234567890123456.123456789012"),
        Decimal("0.000000000001"),
        Decimal("-5.5"),
        None,
    ]
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")
    prepare(database, "1.2.3")
    with Session(database) as session:
        add_run(session)
        session.flush()
        rows: list[dict[str, object]] = [
            {"run_id": "r", "period": 1, "name": f"m{n}", "key": "", "value": value}
            for n, value in enumerate(values)
        ]
        insert_rows(session, {Measure: rows})
        session.commit()
    with Session(database) as session:
        read = list(session.scalars(select(Measure.value).order_by(Measure.name)))
    database.dispose()

    assert read == values
    assert decimal_text(cast(Decimal, read[0])) == (
        "12345678901234567890123456.123456789012"
    )


def test_a_decimal_of_39_digits_is_stored_with_12_places():
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")
    prepare(database, "1.2.3")
    with Session(database) as session:
        add_run(session)
        session.flush()
        value = Decimal("12345678901234567890123456.1234567890120")
        row: dict[str, object] = {
            "run_id": "r",
            "period": 1,
            "name": "m",
            "key": "",
            "value": value,
        }
        insert_rows(session, {Measure: [row]})
        session.commit()
    with Session(database) as session:
        read = session.scalars(select(Measure.value)).one()
    database.dispose()

    assert (
        decimal_text(cast(Decimal, read)) == "12345678901234567890123456.123456789012"
    )


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(json_values)
def test_a_json_column_gives_back_its_value_with_exact_decimals(value: object):
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")
    prepare(database, "1.2.3")
    with Session(database) as session:
        session.add(Manifest(id="m", content={"value": value}, linear=True))
        session.commit()
    with Session(database) as session:
        manifest = session.get_one(Manifest, "m")
        read = manifest.content
    database.dispose()

    assert floats_in(read) == []
    assert write_json(read) == write_json({"value": value})


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(decimals_of_the_record)
def test_a_decimal_column_gives_back_its_value_and_text(value: Decimal):
    database = create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")
    prepare(database, "1.2.3")
    with Session(database) as session:
        add_run(session)
        session.add(
            LedgerEntry(
                run_id="r",
                period=1,
                position=1,
                step="close_period",
                kind="storage_cost",
                amount=value,
                cash_after=value,
                reference="main.chip",
            )
        )
        session.commit()
    with Session(database) as session:
        read = session.get_one(LedgerEntry, ("r", 1, 1)).amount
    database.dispose()

    assert isinstance(read, Decimal)
    assert read == value
    assert decimal_text(read) == decimal_text(value)

import hashlib
import io
import json
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from factories import (
    Client,
    api_client,
    buy,
    database_file,
    engine_of,
    example_count,
    get_message_by_message,
    post,
    records,
    run_to_the_end,
    run_with_drawn_decisions,
    seeds,
    small_factories,
    start_run,
    submit,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import JSON, Numeric
from sqlalchemy.orm import Session
from starlette.types import Message

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.models.operation import (
    Operation,
    OperationBody,
    OperationIdentity,
)
from factory_simulator.api.record.models.run import (
    Event,
    Interaction,
    LedgerEntry,
    Measure,
    Outcome,
    Period,
    Result,
    Run,
    Trace,
)
from factory_simulator.api.record.models.run import World as WorldRow
from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.api.record.repositories.operations import (
    append_body,
    create_operation,
)
from factory_simulator.api.record.transport import export_transport
from factory_simulator.api.services.runs import export

FactoryBodies = tuple[dict[str, Any], dict[str, Any]]
TABLES: tuple[type[Base], ...] = (
    Period,
    Event,
    LedgerEntry,
    Outcome,
    Measure,
    Trace,
    WorldRow,
    Result,
    Interaction,
)
FILES = {
    *(f"{table.__tablename__}.parquet" for table in TABLES),
    "manifest.json",
    "scenario.json",
    "run.json",
    "operations.parquet",
    "operation_bodies.parquet",
    "operations.json",
}


def export_of(client: Client, run_id: str) -> tuple[Any, dict[str, bytes]]:
    response = client.get(f"/api/v1/runs/{run_id}/export")
    if response.status_code != 200:
        return response, {}
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return response, {name: archive.read(name) for name in archive.namelist()}


def parquet_rows(content: bytes) -> tuple[list[dict[str, Any]], dict[str, str]]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "table.parquet"
        path.write_bytes(content)
        with duckdb.connect() as connection:
            relation = connection.read_parquet(str(path))
            names = relation.columns
            types = {
                name: str(kind)
                for name, kind in zip(names, relation.types, strict=True)
            }
            rows = [dict(zip(names, row, strict=True)) for row in relation.fetchall()]
    return rows, types


def as_exported(table: type[Base], row: dict[str, Any]) -> dict[str, Any]:
    exported = dict(row)
    for column in table.__table__.columns:
        value = row[column.key]
        if isinstance(column.type, JSON) and value is not None:
            exported[column.key] = write_json(value).decode()
    return exported


def test_an_unfinished_or_unknown_run_is_not_exported():
    with api_client() as client:
        run = start_run(client)
        during, _ = export_of(client, run["id"])
        unknown, _ = export_of(client, "abc")

    assert (during.status_code, during.json()) == (
        409,
        {"detail": "run: the run is not finished"},
    )
    assert (unknown.status_code, unknown.json()) == (
        404,
        {"detail": "run_id: unknown run abc"},
    )


def test_a_finished_run_is_exported_as_one_zip_of_its_tables_and_inputs():
    with api_client() as client:
        run = start_run(client, seed=2**128 - 1)
        post(
            client,
            f"/runs/{run['id']}/checks",
            {"period": 1, "decisions": []},
        )
        submit(client, run["id"], 2, [])
        run_to_the_end(client, run)
        response, files = export_of(client, run["id"])
        interactions = records(client, Interaction, run_id=run["id"])
        [stored] = records(client, Run, id=run["id"])
        [scenario] = records(client, Scenario, id=run["scenario_id"])
        [manifest] = records(client, Manifest, id=scenario["manifest_id"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f'filename="{run["id"]}.zip"' in response.headers["content-disposition"]
    assert set(files) == FILES
    described = json.loads(files["run.json"], parse_float=Decimal)
    expected = stored | {"seed": 2**128 - 1}
    assert described == json.loads(write_json(expected), parse_float=Decimal)
    assert described["id"] == run["id"]
    assert files["manifest.json"] == write_json(manifest["content"])
    assert files["scenario.json"] == write_json(scenario["content"])
    rows, _ = parquet_rows(files["interactions.parquet"])
    assert [(row["position"], row["kind"]) for row in rows] == [
        (1, "check"),
        (2, "refusal"),
    ]
    assert len(rows) == len(interactions)


@pytest.mark.parametrize("send_fails", [False, True])
def test_an_export_leaves_no_folder_whether_its_send_succeeds_or_fails(
    send_fails: bool, monkeypatch: pytest.MonkeyPatch
):
    with tempfile.TemporaryDirectory() as directory, api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run)
        monkeypatch.setattr(tempfile, "tempdir", directory)
        folders: list[Path] = []
        export_run = export.export_run

        def recorded(session: Session, run_id: str, folder: Path) -> Path:
            folders.append(folder)
            return export_run(session, run_id, folder)

        monkeypatch.setattr(export, "export_run", recorded)
        sent: list[bytes] = []

        def read(message: Message) -> None:
            if message["type"] == "http.response.body":
                if send_fails:
                    raise OSError("the client went away")
                sent.append(message["body"])

        path = f"/runs/{run['id']}/export"
        if send_fails:
            with pytest.raises(OSError, match="the client went away"):
                get_message_by_message(client, path, read)
        else:
            get_message_by_message(client, path, read)
        left = list(Path(directory).iterdir())

    assert [folder.parent for folder in folders] == [Path(directory)]
    assert left == []
    if not send_fails:
        with zipfile.ZipFile(io.BytesIO(b"".join(sent))) as archive:
            assert set(archive.namelist()) == FILES


def test_json_columns_are_text_and_decimals_have_12_places():
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run)
        _, files = export_of(client, run["id"])

    numeric: list[str] = []
    for table in TABLES:
        rows, types = parquet_rows(files[f"{table.__tablename__}.parquet"])
        for column in table.__table__.columns:
            if isinstance(column.type, JSON):
                assert types[column.key] == "VARCHAR", column.key
                assert all(
                    isinstance(row[column.key], str)
                    for row in rows
                    if row[column.key] is not None
                ), column.key
            elif isinstance(column.type, Numeric) and column.type.scale is not None:
                assert types[column.key] == "DECIMAL(38,12)", column.key
                numeric.append(f"{table.__tablename__}.{column.key}")
    assert {"ledger.amount", "measures.value", "results.profit"} <= set(numeric)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_every_exported_table_holds_the_rows_of_the_run(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    with api_client() as client:
        run_id = run_with_drawn_decisions(client, factory, seed, data)
        _, files = export_of(client, run_id)
        stored = {
            table.__tablename__: records(client, table, run_id=run_id)
            for table in TABLES
        }

    for table in TABLES:
        rows, _ = parquet_rows(files[f"{table.__tablename__}.parquet"])
        assert rows == [as_exported(table, row) for row in stored[table.__tablename__]]


@pytest.mark.slow
def test_the_finished_export_keeps_private_exact_transitions_in_execution_order():
    with api_client() as client:
        run = start_run(client)
        assert submit(client, run["id"], 1, [buy("6")])[0] == 200
        run_to_the_end(client, run | {"period": 2})
        _, files = export_of(client, run["id"])

    rows, types = parquet_rows(files["traces.parquet"])
    first = [row for row in rows if row["period"] == 1]
    assert [row["position"] for row in first] == list(range(1, 8))
    assert [row["step"] for row in first if row["kind"] == "step"] == [
        "receive_deliveries",
        "apply_events",
        "build_observation",
        "make_decisions",
        "execute_decisions",
        "close_period",
    ]
    [bought] = [row for row in first if row["kind"] == "buy"]
    assert bought["decision_id"] == "1-1"
    assert json.loads(bought["input"])["quantity"] == 6
    order = json.loads(bought["after"], parse_float=Decimal)["plant"][
        "supplier_orders"
    ][0]
    assert order["arrival"] == 3
    assert order["unit_price"] == Decimal("0.5")
    assert order["cancelled"] == 0
    assert json.loads(first[-1]["after"])["tallies"]
    assert types["before"] == types["after"] == "VARCHAR"


@pytest.mark.slow
def test_repeated_exports_have_finite_operation_cutoffs_and_external_archive_bodies():
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run)
        _, first = export_of(client, run["id"])
        _, second = export_of(client, run["id"])
        exports = records(client, Operation, path=f"/api/v1/runs/{run['id']}/export")

    first_operations = json.loads(first["operations.json"])
    second_operations = json.loads(second["operations.json"])
    assert first_operations["cutoff"] == exports[0]["position"] - 1
    assert second_operations["cutoff"] == exports[1]["position"] - 1
    operations, _ = parquet_rows(second["operations.parquet"])
    assert max(row["position"] for row in operations) == exports[0]["position"]
    bodies, types = parquet_rows(second["operation_bodies.parquet"])
    assert types["body"] == "BLOB"
    assert not any(
        row["operation_id"] == exports[0]["position"] and row["direction"] == "response"
        for row in bodies
    )
    references = second_operations["external_bodies"]
    assert references
    assert {row["operation_id"] for row in references} == {exports[0]["position"]}
    assert all(
        row["direction"] == "response" and len(row["digest"]) == 64
        for row in references
    )


@pytest.mark.slow
def test_the_offline_transport_bundle_retains_export_bytes_and_no_run_operations(
    tmp_path: Path,
):
    with database_file() as url:
        with api_client(url) as client:
            missing = client.post("/api/v1/runs/unknown/decisions", content=b" \xff ")
            run = start_run(client)
            run_to_the_end(client, run)
            first_response, _ = export_of(client, run["id"])
            _, second = export_of(client, run["id"])
            exports = records(
                client, Operation, path=f"/api/v1/runs/{run['id']}/export"
            )
        destination = tmp_path / "transport.zip"
        assert (
            export_transport(Path(url.removeprefix("duckdb:///")), destination)
            == destination
        )
        with zipfile.ZipFile(destination) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}

    metadata = json.loads(files["operations.json"])
    assert metadata["kind"] == "transport"
    operations, _ = parquet_rows(files["operations.parquet"])
    assert operations[-1]["kind"] == "shutdown"
    assert metadata["cutoff"] == operations[-1]["position"]
    bodies, _ = parquet_rows(files["operation_bodies.parquet"])
    references = json.loads(second["operations.json"])["external_bodies"]
    indexed = {
        (row["operation_id"], row["direction"], row["position"]): row for row in bodies
    }
    for reference in references:
        stored = indexed[
            (reference["operation_id"], reference["direction"], reference["position"])
        ]
        assert stored["digest"] == reference["digest"]
        assert len(stored["body"]) == reference["size"]
    first_bytes = b"".join(
        row["body"]
        for row in bodies
        if row["operation_id"] == exports[0]["position"]
        and row["direction"] == "response"
    )
    assert first_bytes == first_response.content
    [unknown] = [row for row in operations if row["requested_run_id"] == "unknown"]
    assert unknown["run_id"] is None
    assert unknown["status_code"] == missing.status_code == 404
    assert (
        b"".join(
            row["body"]
            for row in bodies
            if row["operation_id"] == unknown["position"]
            and row["direction"] == "request"
        )
        == b" \xff "
    )


@pytest.mark.slow
def test_transport_verification_checks_archived_references_after_a_rehashed_change(
    tmp_path: Path,
):
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            run_to_the_end(client, run)
            export_of(client, run["id"])
            export_of(client, run["id"])
            exports = records(
                client, Operation, path=f"/api/v1/runs/{run['id']}/export"
            )
            with Session(engine_of(client)) as session:
                body = session.get(
                    OperationBody, (exports[0]["position"], "response", 1)
                )
                assert body is not None
                changed = bytearray(body.body)
                changed[10] ^= 1
                body.body = bytes(changed)
                body.digest = hashlib.sha256(body.body).hexdigest()
                session.commit()
        destination = tmp_path / "invalid.zip"
        with pytest.raises(ValueError, match="external body reference differs"):
            export_transport(Path(url.removeprefix("duckdb:///")), destination)

    assert not destination.exists()


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(st.binary(max_size=512))
def test_raw_request_bytes_survive_a_finished_run_export(body: bytes):
    with api_client() as client:
        run = start_run(client)
        path = f"/api/v1/runs/{run['id']}/checks"
        client.post(path, content=body)
        [operation] = records(client, Operation, path=path)
        stored = records(
            client,
            OperationBody,
            operation_id=operation["position"],
            direction="request",
        )
        run_to_the_end(client, run)
        _, files = export_of(client, run["id"])

    rows, _ = parquet_rows(files["operation_bodies.parquet"])
    exported = [
        row["body"]
        for row in rows
        if row["operation_id"] == operation["position"]
        and row["direction"] == "request"
    ]
    assert b"".join(row["body"] for row in stored) == body
    assert b"".join(exported) == body


@pytest.mark.slow
@pytest.mark.parametrize(
    "corruption",
    ["empty-identity", "missing-facts", "bad-direction", "oversized", "empty-chunk"],
)
def test_transport_verification_refuses_inconsistent_identity_and_body_rows(
    tmp_path: Path, corruption: str
):
    with database_file() as url:
        with api_client(url) as client:
            database = engine_of(client)
            if corruption == "empty-identity":
                with Session(database) as session:
                    session.add(OperationIdentity())
                    session.commit()
            else:
                operation = create_operation(database, "GET", "/missing", None)
                if corruption in {"missing-facts", "bad-direction"}:
                    direction = (
                        "nonsense" if corruption == "bad-direction" else "request"
                    )
                    append_body(database, operation.position, direction, 0, b"orphan")
                    if corruption == "missing-facts":
                        with Session(database) as session:
                            stored = session.get(Operation, operation.position)
                            assert stored is not None
                            session.delete(stored)
                            session.commit()
                else:
                    body = b"x" * 65537 if corruption == "oversized" else b""
                    with Session(database) as session:
                        session.add(
                            OperationBody(
                                operation_id=operation.position,
                                direction="request",
                                position=1,
                                body=body,
                                digest=hashlib.sha256(body).hexdigest(),
                            )
                        )
                        session.commit()
        destination = tmp_path / f"{corruption}.zip"
        with pytest.raises(ValueError, match="operation"):
            export_transport(Path(url.removeprefix("duckdb:///")), destination)

    assert not destination.exists()


@pytest.mark.slow
def test_transport_verification_keeps_legitimate_sequence_gaps(tmp_path: Path):
    with database_file() as url:
        with api_client(url) as client, Session(engine_of(client)) as session:
            session.add(OperationIdentity())
            session.flush()
            session.rollback()
        destination = export_transport(
            Path(url.removeprefix("duckdb:///")), tmp_path / "gap.zip"
        )
        with zipfile.ZipFile(destination) as archive:
            operations, _ = parquet_rows(archive.read("operations.parquet"))

    assert [row["position"] for row in operations] == [1, 3]

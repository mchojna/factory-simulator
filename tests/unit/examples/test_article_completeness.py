import json
from pathlib import Path

import pytest

from scripts.reproduction.article import context, verify_results
from scripts.reproduction.article.__main__ import compare_examples


def write_json(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def example_pair(tmp_path: Path) -> tuple[Path, Path]:
    data, output = tmp_path / "data", tmp_path / "output"
    for root in (data, output):
        write_json(
            root, "examples/order-fulfilment/baseline-result.json", {"profit": 1}
        )
        write_json(
            root,
            "examples/reference/micro-exact.json",
            {
                "result": {"profit": 2},
                "periods": [1],
                "world": {"seed": 7},
            },
        )
    return data, output


def test_examples_accept_complete_records_and_ignore_only_known_summaries(
    tmp_path: Path,
):
    data, output = example_pair(tmp_path)
    write_json(
        data, "examples/order-fulfilment/demonstration-results.json", {"time": 1}
    )
    write_json(
        output, "examples/order-fulfilment/demonstration-results.json", {"time": 2}
    )
    write_json(output, "examples/reference/reference-example-results.json", {"time": 3})
    compare_examples(data, output)
    checks = json.loads((output / "example-comparison.json").read_text())
    assert len(checks) == 4
    assert all(checks.values())


@pytest.mark.parametrize("change", ["missing", "extra", "empty", "hidden-extra"])
def test_examples_reject_incomplete_or_extra_records(tmp_path: Path, change: str):
    data, output = example_pair(tmp_path)
    if change in ("missing", "empty"):
        (output / "examples/reference/micro-exact.json").unlink()
    if change == "empty":
        (output / "examples/order-fulfilment/baseline-result.json").unlink()
    if change == "extra":
        write_json(output, "examples/unexpected.json", {})
    if change == "hidden-extra":
        write_json(output, "examples/unexpected/demonstration-results.json", {})
    with pytest.raises(AssertionError, match="inventory differs"):
        compare_examples(data, output)
    assert not (output / "example-comparison.json").exists()


def test_examples_reject_empty_archive(tmp_path: Path):
    with pytest.raises(AssertionError, match="expected 0 records"):
        compare_examples(tmp_path / "data", tmp_path / "output")


def test_examples_still_reject_changed_result(tmp_path: Path):
    data, output = example_pair(tmp_path)
    write_json(output, "examples/order-fulfilment/baseline-result.json", {"profit": 99})
    with pytest.raises(AssertionError, match="article examples differ"):
        compare_examples(data, output)


def test_notice_accepts_complete_inventory(tmp_path: Path):
    write_json(tmp_path, "first.json", {})
    write_json(tmp_path, "second.json", {})
    verify_results.check_case_inventory(
        {"first", "second"}, {"first", "second"}, tmp_path, tmp_path, "matrix"
    )


def test_notice_rejects_empty_expected_inventory(tmp_path: Path):
    with pytest.raises(AssertionError, match="archive inventory differs"):
        verify_results.check_case_inventory(set(), set(), tmp_path, tmp_path, "matrix")


@pytest.mark.parametrize("group", ["matrix", "extension"])
@pytest.mark.parametrize(
    "change",
    ["missing-summary", "extra-summary", "missing-file", "extra-file", "missing-both"],
)
def test_notice_main_rejects_incomplete_or_extra_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, group: str, change: str
):
    data, output = tmp_path / "data", tmp_path / "output"
    monkeypatch.setattr(context, "DATA", data)
    monkeypatch.setattr(context, "OUTPUT", output)
    layouts = {
        "matrix": ("recorded-results.json", "results.json", "records"),
        "extension": (
            "recorded-extension-results.json",
            "extension-results.json",
            "extension-records",
        ),
    }
    for name, (archived, generated, folder) in layouts.items():
        summary: dict[str, dict[str, object]] = {"cases": {"first": {}, "second": {}}}
        write_json(data / "notice", archived, summary)
        archived_folder = "recorded" if name == "matrix" else "recorded-extension"
        write_json(data / "notice" / archived_folder, "first.json", {})
        write_json(data / "notice" / archived_folder, "second.json", {})
        write_json(output / "notice" / folder, "first.json", {})
        second = write_json(output / "notice" / folder, "second.json", {})
        if name == group:
            if change in ("missing-summary", "missing-both"):
                del summary["cases"]["second"]
            if change == "extra-summary":
                summary["cases"]["third"] = {}
            if change in ("missing-file", "missing-both"):
                second.unlink()
            if change == "extra-file":
                write_json(output / "notice" / folder, "third.json", {})
        write_json(output / "notice", generated, summary)
    with pytest.raises(AssertionError, match="inventory differs"):
        verify_results.main()
    assert not (output / "notice/verification.json").exists()


def test_notice_accepts_archived_auxiliary_files(tmp_path: Path):
    archive, output = tmp_path / "archive", tmp_path / "output"
    for root in (archive, output):
        for name in ("first.json", "factory-manifest.json", "factory-scenario.json"):
            write_json(root, name, {})
    verify_results.check_case_inventory({"first"}, {"first"}, archive, output, "matrix")
    (output / "factory-manifest.json").unlink()
    with pytest.raises(AssertionError, match="records inventory differs"):
        verify_results.check_case_inventory(
            {"first"}, {"first"}, archive, output, "matrix"
        )

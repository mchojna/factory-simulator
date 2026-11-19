import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from examples.coordinated_planning import MODEL, evidence
from examples.coordinated_planning.recorded import RecordedProvider
from examples.coordinated_planning.run import main

LIVE_RATES = [
    "--budget-usd",
    "1",
    "--input-usd-per-million",
    "1.25",
    "--output-usd-per-million",
    "5",
]


# An archive of the package with the files and their texts, its manifest listing the
# digests of the manifest files.
def package_archive(
    path: Path, files: dict[str, str], manifest_files: dict[str, str] | None = None
) -> Path:
    listed = files if manifest_files is None else manifest_files
    manifest = {
        name: hashlib.sha256(text.encode()).hexdigest() for name, text in listed.items()
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{evidence.PREFIX}/{evidence.MANIFEST}", json.dumps(manifest))
        for name, text in files.items():
            archive.writestr(f"{evidence.PREFIX}/{name}", text)
    return path


def test_an_archive_whose_files_match_its_manifest_is_extracted(tmp_path: Path):
    archive = package_archive(tmp_path / "evidence.zip", {"README.txt": "guide"})

    package = evidence.extract(tmp_path / "new", archive)

    assert package == tmp_path / "new" / evidence.PREFIX
    assert (package / "README.txt").read_text() == "guide"


def test_a_file_that_differs_from_the_manifest_is_refused(tmp_path: Path):
    archive = package_archive(
        tmp_path / "evidence.zip", {"README.txt": "changed"}, {"README.txt": "guide"}
    )

    with pytest.raises(ValueError, match=r"1 files differ, first README\.txt"):
        evidence.extract(tmp_path / "new", archive)


def test_a_missing_archive_is_refused(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        evidence.extract(tmp_path / "new", tmp_path / "missing.zip")

    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("member", ["../escape", "/absolute", "other-root/file"])
def test_a_member_outside_the_package_folder_is_refused(tmp_path: Path, member: str):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr(member, "fixture")

    with pytest.raises(ValueError, match="path leaves"):
        evidence.extract(tmp_path / "new", archive)

    assert not (tmp_path / "new").exists()


def test_an_existing_destination_is_left_as_it_is(tmp_path: Path):
    archive = package_archive(tmp_path / "evidence.zip", {"README.txt": "guide"})
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep").write_text("unchanged")

    with pytest.raises(FileExistsError):
        evidence.extract(destination, archive)

    assert (destination / "keep").read_text() == "unchanged"


def test_a_request_that_differs_from_its_record_is_refused(tmp_path: Path):
    request: dict[str, object] = {
        "kind": "provider-request",
        "call_id": 1,
        "period": 1,
        "messages": [],
        "request": {
            "model": MODEL,
            "messages": [],
            "reasoning_effort": "low",
            "service_tier": "default",
            "max_completion_tokens": 8192,
        },
    }
    reply: dict[str, object] = {
        "kind": "provider-response",
        "call_id": 1,
        "period": 1,
        "reply": {},
    }
    (tmp_path / "model-calls.jsonl").write_text(
        f"{json.dumps(request)}\n{json.dumps(reply)}\n"
    )
    provider = RecordedProvider(tmp_path)

    with pytest.raises(RuntimeError, match="differs from its record"):
        provider.complete(
            [{"role": "user", "content": "changed"}], {"max_output_tokens": 8192}
        )

    assert provider.index == 0


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ([], "one of the arguments --offline --live is required"),
        (["--offline"], "--archive: is required"),
        (["--live", "--archive", "evidence.zip"], "--archive: applies only"),
        (["--live"], "--live: requires --budget-usd"),
        (["--live", *LIVE_RATES], "OPENAI_API_KEY"),
    ],
    ids=[
        "no-mode",
        "offline-without-archive",
        "live-with-archive",
        "no-rates",
        "no-key",
    ],
)
def test_a_command_without_its_mode_inputs_is_refused_before_any_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    error: str,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = tmp_path / "output"

    with pytest.raises(SystemExit):
        main([*arguments, "--output", str(output)])

    assert error in capsys.readouterr().err
    assert not output.exists()

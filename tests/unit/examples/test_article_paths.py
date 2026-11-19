import hashlib
import json
from pathlib import Path

import pytest

from scripts.reproduction.article.__main__ import validate_paths


def package_at(root: Path) -> Path:
    root.mkdir()
    (root / "record.json").write_text("{}")
    (root / "SHA256SUMS.json").write_text(
        json.dumps({"record.json": hashlib.sha256(b"{}").hexdigest()})
    )
    return root


def test_rejects_output_inside_evidence(tmp_path: Path):
    data = package_at(tmp_path / "data")
    with pytest.raises(ValueError, match="non-overlapping"):
        validate_paths(data, data / "output")


def test_rejects_modified_evidence(tmp_path: Path):
    data = package_at(tmp_path / "data")
    (data / "record.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="inventory"):
        validate_paths(data, tmp_path / "output")


def test_rejects_output_reuse(tmp_path: Path):
    data = package_at(tmp_path / "data")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(FileExistsError):
        validate_paths(data, output)


def test_valid_paths_do_not_modify_data(tmp_path: Path):
    data = package_at(tmp_path / "data")
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    validate_paths(data, tmp_path / "output")
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}
    assert not (tmp_path / "output").exists()

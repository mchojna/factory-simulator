import re
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.mark.slow
def test_documentation_builds_the_public_site(tmp_path: Path):
    output = tmp_path / "public site"
    result = subprocess.run(
        ["bash", str(REPOSITORY / "scripts" / "build_docs.sh"), str(output)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / "index.html").is_file()
    assert (output / "rules/index.html").is_file()
    assert not (output / "pl").exists()
    assert not (output / "documentation").exists()

    landing = (output / "index.html").read_text()
    assert 'hreflang="pl"' not in landing
    assert re.search(r'href="(?:\./)?assets/[^\"]+\.css"', landing)

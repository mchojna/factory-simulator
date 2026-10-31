import re
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
SITE_URL = "https://mchojna.github.io/factory-simulator"


@pytest.mark.slow
def test_collection_builds_assemble_the_bilingual_public_site(tmp_path: Path):
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
    assert (output / "pl/index.html").is_file()
    assert (output / "documentation/index.html").is_file()
    assert (output / "rules/index.html").is_file()
    assert (output / "pl/rules/index.html").is_file()

    development_english = (output / "index.html").read_text()
    hub = (output / "documentation/index.html").read_text()
    assert f'href="{SITE_URL}/"' in hub
    assert f'href="{SITE_URL}/pl/"' in hub

    assert "English and Polish development guides" not in development_english
    assert 'href="/factory-simulator/pl/" hreflang="pl"' in development_english
    assert re.search(r'href="(?:\./)?assets/[^\"]+\.css"', development_english)

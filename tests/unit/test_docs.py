import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK = re.compile(r"(!?\[[^\]]*\])\(([^)]*)\)")
# An entry of a Contents list: a link or a code span that names a file or folder.
CONTENTS_ENTRY = re.compile(r"^- (?:\[[^\]]*\]\(([^)]*)\)|`([^`]*)`)")
PALETTE = {
    "classDef item fill:#3284D8,stroke:#3284D8,color:#000000",
    "classDef place fill:#AF751D,stroke:#AF751D,color:#000000",
    "classDef partner fill:#3D9250,stroke:#3D9250,color:#000000",
    "classDef system fill:#9869DE,stroke:#9869DE,color:#000000",
    "classDef disruption fill:#E8473C,stroke:#E8473C,color:#000000",
}
EXCLUDED_DIRECTORIES = {
    ".agents",
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site",
    "venv",
}


def directories_with_files(root: Path) -> set[Path]:
    with_files: set[Path] = set()
    for current, directories, files in os.walk(root):
        folder = Path(current)
        relative = folder.relative_to(root)
        if relative.parts and relative.parts[0] == "data" and len(relative.parts) > 1:
            directories.clear()
            continue
        directories[:] = [
            directory
            for directory in directories
            if directory not in EXCLUDED_DIRECTORIES
        ]
        if files:
            parent = folder
            while parent == root or root in parent.parents:
                with_files.add(parent)
                if parent == root:
                    break
                parent = parent.parent

    return with_files


def directories_missing_readme(root: Path) -> set[Path]:
    return {
        folder
        for folder in directories_with_files(root)
        if not (folder / "README.md").is_file()
        and not (folder == root / ".github" and (folder / "OVERVIEW.md").is_file())
    }


# Every file of the repository that git tracks or does not ignore, relative to the
# root.
def repository_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [
        Path(name) for name in listing.split("\0") if name and (ROOT / name).is_file()
    ]


# The first path part of each entry of the `## Contents` list of a README, or None
# when the README has no such list.
def contents_names(text: str) -> set[str] | None:
    section = re.search(r"(?ms)^## Contents\n(.*?)(?=^## |\Z)", text)
    if section is None:
        return None
    names: set[str] = set()
    for line in section[1].splitlines():
        entry = CONTENTS_ENTRY.match(line)
        if entry:
            names.add(Path(entry[1] or entry[2]).parts[0])
    return names


# Each README with a Contents list whose entries differ from the files and folders
# beside it, with the names it misses and the names it lists in excess.
def contents_mismatches(
    files: list[Path], read: Callable[[Path], str]
) -> dict[Path, tuple[list[str], list[str]]]:
    children: dict[Path, set[str]] = {}
    for path in files:
        for parent in path.parents:
            children.setdefault(parent, set()).add(path.parts[len(parent.parts)])
    mismatches: dict[Path, tuple[list[str], list[str]]] = {}
    for readme in sorted(path for path in files if path.name == "README.md"):
        listed = contents_names(read(readme))
        if listed is None:
            continue
        present = children[readme.parent] - {"README.md"}
        if listed != present:
            mismatches[readme] = (sorted(present - listed), sorted(listed - present))
    return mismatches


def fenced_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    marker: str | None = None
    info = ""
    lines: list[str] = []
    for line in text.splitlines():
        if marker is None:
            opening = FENCE.match(line)
            if opening:
                marker = opening[1]
                info = opening[2].strip()
                lines = []
        elif re.match(rf"^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}\s*$", line):
            blocks.append((info, "\n".join(lines)))
            marker = None
        else:
            lines.append(line)
    return blocks


def outline(text: str) -> tuple[list[tuple[int, str]], int]:
    headings: list[tuple[int, str]] = []
    mermaid_count = 0
    fence: str | None = None
    for line in text.splitlines():
        if fence is None:
            opening = FENCE.match(line)
            if opening:
                fence = opening[1]
                mermaid_count += opening[2].strip() == "mermaid"
                continue
            heading = HEADING.match(line)
            if heading:
                headings.append((len(heading[1]), heading[2]))
        elif re.match(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$", line):
            fence = None
    return headings, mermaid_count


def code_blocks(text: str) -> list[str]:
    return [f"```{info}\n{body}\n```" for info, body in fenced_blocks(text)]


def anchor_of(heading: str) -> str:
    heading = re.sub(r"`([^`]*)`", r"\1", heading).lower()
    heading = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", heading)


def pages_of() -> set[Path]:
    return {path.relative_to(DOCS) for path in DOCS.rglob("*.md")}


def ascii_violation_is_reported(path: str, text: str) -> bool:
    configuration = (ROOT / ".pre-commit-config.yaml").read_text()
    ascii_hook = configuration.split("- id: ascii-only", maxsplit=1)[1].split(
        "- id: commit-subject", maxsplit=1
    )[0]
    match = re.search(r"(?m)^\s+exclude: (.+)$", ascii_hook)
    assert match is not None
    excluded = re.compile(match[1])
    return bool(re.search(r"[^\x00-\x7f]", text)) and not excluded.fullmatch(path)


def anchors_of(text: str) -> set[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for _, heading in outline(text)[0]:
        anchor = anchor_of(heading)
        number = occurrences.get(anchor, 0)
        suffix = "" if number == 0 else f"-{number}"
        anchors.add(f"{anchor}{suffix}")
        occurrences[anchor] = number + 1
    return anchors


def test_outline_ignores_headings_inside_fences_and_counts_mermaid():
    page = "\n".join(
        [
            "# A",
            "```python",
            "# not a heading",
            "```",
            "## B",
            "~~~mermaid",
            "flowchart LR",
            "classDef item fill:#3284D8,stroke:#3284D8,color:#000000",
            "~~~",
        ]
    )

    assert outline(page) == ([(1, "A"), (2, "B")], 1)


def test_code_blocks_keep_fence_and_contents():
    page = "```python\nprint(1)\n```\n```mermaid\nflowchart LR\n```"

    assert code_blocks(page) == [
        "```python\nprint(1)\n```",
        "```mermaid\nflowchart LR\n```",
    ]


def test_anchor_drops_punctuation():
    assert (
        anchor_of('Cash and profit: "steady-market"') == "cash-and-profit-steady-market"
    )


def test_documentation_has_a_landing_page():
    assert pages_of()
    assert Path("README.md") in pages_of()
    assert Path("index.md") not in pages_of()


def test_maintained_directories_have_readmes():
    assert directories_missing_readme(ROOT) == set()


def test_readme_coverage_skips_generated_trees_and_finds_nested_sources(
    tmp_path: Path,
):
    (tmp_path / "README.md").write_text("# Repository\n")
    maintained = tmp_path / "maintained"
    maintained.mkdir()
    (maintained / "README.md").write_text("# Maintained\n")
    nested = maintained / "nested"
    nested.mkdir()
    (nested / "module.py").write_text("value = 1\n")
    generated = tmp_path / "site" / "generated"
    generated.mkdir(parents=True)
    (generated / "page.html").write_text("generated\n")
    environment = tmp_path / ".venv" / "lib"
    environment.mkdir(parents=True)
    (environment / "module.py").write_text("installed\n")
    skills = tmp_path / ".agents" / "skills" / "tool"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("installed skill\n")
    repository_data = tmp_path / "data" / "records"
    repository_data.mkdir(parents=True)
    (repository_data / "runs.duckdb").write_bytes(b"generated")
    internals = tmp_path / ".git" / "objects"
    internals.mkdir(parents=True)
    (internals / "object").write_bytes(b"git object")

    assert directories_missing_readme(tmp_path) == {nested}


def test_every_contents_list_names_each_file_and_folder_beside_its_readme():
    assert (
        contents_mismatches(repository_files(), lambda path: (ROOT / path).read_text())
        == {}
    )


def test_a_contents_list_check_finds_missing_and_excess_entries():
    pages = {
        Path("README.md"): "# Repository\n",
        Path("tests/README.md"): (
            "# Tests\n\n## Contents\n\n- [unit/](unit/README.md): the unit tests.\n"
            "- [gone.py](gone.py): a file that is not there.\n\n## Entry point\n"
        ),
        Path("tests/unit/README.md"): (
            "# Unit\n\n## Contents\n\n- `test_one.py` checks one thing.\n"
        ),
    }
    files = [*pages, Path("tests/conftest.py"), Path("tests/unit/test_one.py")]

    assert contents_mismatches(files, lambda path: pages[path]) == {
        Path("tests/README.md"): (["conftest.py"], ["gone.py"])
    }


def test_readme_and_index_sources_build_to_unique_pages():
    destinations = [
        page.parent / "index.html"
        if page.name in {"README.md", "index.md"}
        else page.with_suffix(".html")
        for page in pages_of()
    ]
    assert len(destinations) == len(set(destinations))


def test_every_page_has_a_title_and_no_heading_below_level_3():
    for page in pages_of():
        text = (DOCS / page).read_text()
        headings = outline(text)[0]
        first_line = next(line for line in text.splitlines() if line.strip())
        assert headings[0][0] == 1, page
        assert first_line.startswith("# "), page
        assert sum(level == 1 for level, _ in headings) == 1, page
        assert all(level <= 3 for level, _ in headings), page


def test_each_page_has_at_most_300_lines():
    for page in pages_of():
        line_count = len((DOCS / page).read_text().splitlines())
        assert line_count <= 300, (page, line_count)


def test_no_heading_is_a_question():
    for page in pages_of():
        headings = outline((DOCS / page).read_text())[0]
        assert all(not heading.endswith("?") for _, heading in headings), page


def test_decision_headings_use_titles():
    headings = outline((DOCS / "rules/decisions.md").read_text())[0]
    assert [heading for level, heading in headings if level == 3] == [
        "Ship",
        "Cancel",
        "Transfer",
        "Repair",
        "Produce",
        "Buy",
    ]


def test_every_rule_page_ends_with_a_worked_example():
    rule_pages = {
        page
        for page in pages_of()
        if page.parent == Path("rules") and page.name != "README.md"
    }
    rule_pages.add(Path("benchmark/score.md"))
    for page in rule_pages:
        headings = outline((DOCS / page).read_text())[0]
        level_two = [heading for level, heading in headings if level == 2]
        assert level_two[-1] == "Worked example", page


def test_every_guide_starts_with_smallest_example_and_ends_with_errors():
    guide_pages = {
        Path("start/quick-start.md"),
        Path("benchmark/playing-a-run.md"),
        Path("benchmark/stress-test.md"),
        *(
            page
            for page in pages_of()
            if page.parent == Path("guides") and page.name != "README.md"
        ),
    }
    for page in guide_pages:
        headings = outline((DOCS / page).read_text())[0]
        level_two = [heading for level, heading in headings if level == 2]
        assert level_two[0] == "Smallest example", page
        assert level_two[-1] == "Errors", page


def test_every_diagram_class_uses_the_palette():
    for page in pages_of():
        for _, body in fenced_blocks((DOCS / page).read_text()):
            assert all(
                line.strip() in PALETTE
                for line in body.splitlines()
                if line.strip().startswith("classDef ")
            ), page


def test_palette_and_required_diagrams_are_present():
    bodies = {
        page: [
            body
            for info, body in fenced_blocks((DOCS / page).read_text())
            if info == "mermaid"
        ]
        for page in pages_of()
    }
    definitions = {
        line.strip()
        for page_bodies in bodies.values()
        for body in page_bodies
        for line in body.splitlines()
        if line.strip().startswith("classDef ")
    }
    assert definitions == PALETTE
    assert any(
        body.lstrip().startswith("sequenceDiagram")
        for body in bodies[Path("benchmark/playing-a-run.md")]
    )
    assert any(
        body.lstrip().startswith("stateDiagram-v2")
        for body in bodies[Path("rules/production.md")]
    )
    assert any(
        body.lstrip().startswith("gantt")
        for body in bodies[Path("rules/information.md")]
    )


def test_public_readmes_and_root_files_have_valid_relative_links_and_anchors():
    pages = {
        ROOT / "CONTRIBUTING.md",
        ROOT / "CHANGELOG.md",
        ROOT / ".github/OVERVIEW.md",
    }
    pages.update(
        folder / "README.md"
        for folder in directories_with_files(ROOT)
        if (folder / "README.md").is_file()
    )
    for page in sorted(pages):
        filename = page.relative_to(ROOT)
        for _, target in LINK.findall(page.read_text()):
            if target.startswith(("http:", "https:", "mailto:")):
                continue
            path, _, anchor = target.partition("#")
            linked = (page.parent / path).resolve() if path else page
            assert linked.is_file(), (filename, target)
            assert not anchor or anchor in anchors_of(linked.read_text()), (
                filename,
                target,
            )


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "CONTRIBUTING.md",
        "LICENSE.txt",
        "pyproject.toml",
        "CITATION.cff",
        "uv.lock",
    ],
)
def test_author_metadata_allows_original_names(path: str):
    assert not ascii_violation_is_reported(path, "Micha\u0142 Chojna")


@pytest.mark.parametrize(
    "path",
    ["docs/README.md", "src/module.py", "tests/unit/test_docs.py"],
)
def test_source_text_keeps_ascii_policy(path: str):
    assert ascii_violation_is_reported(path, "Micha\u0142 Chojna")

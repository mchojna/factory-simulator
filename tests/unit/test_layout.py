import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[2] / "src" / "factory_simulator"


# Each folder of the package and the packages its modules may not import.
FORBIDDEN = {
    "engine/rules": (
        "engine.steps",
        "engine.decisions",
        "engine.measures",
        "engine.draws",
        "engine.checks",
    ),
    "engine/models": (
        "engine.steps",
        "engine.decisions",
        "engine.measures",
        "engine.rules",
    ),
    "engine/decisions": ("engine.steps", "engine.measures"),
    "engine/measures": ("engine.steps", "engine.decisions"),
    "engine/checks": ("engine.steps", "engine.decisions", "engine.measures"),
    "engine": ("api", "benchmark"),
    "api": ("benchmark",),
    "benchmark": ("engine", "api"),
    "api/routes": ("api.record", "engine"),
    "api/schemas": ("api.services", "api.routes", "api.record"),
    "api/record": ("api.services", "api.routes", "api.schemas"),
    "api/services": ("api.routes",),
    "api/core": ("api.services", "api.routes", "api.record", "api.schemas"),
}


def imported_modules(source: str, package: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module is not None:
                modules.append(node.module)
        elif isinstance(node, ast.ImportFrom):
            # A relative import of level n starts from the package without its
            # last n - 1 parts.
            parts = package.split(".")
            base = ".".join(parts[: len(parts) - (node.level - 1)])
            if node.module is not None:
                modules.append(f"{base}.{node.module}")
            else:
                modules.extend(f"{base}.{alias.name}" for alias in node.names)
    return modules


def package_of(path: Path) -> str:
    return ".".join(("factory_simulator", *path.parent.relative_to(PACKAGE).parts))


@pytest.mark.parametrize(("folder", "forbidden"), FORBIDDEN.items())
def test_no_module_imports_a_layer_above_it(folder: str, forbidden: tuple[str, ...]):
    wrong = [
        (path.relative_to(PACKAGE).as_posix(), module)
        for path in sorted((PACKAGE / folder).rglob("*.py"))
        for module in imported_modules(path.read_text(), package_of(path))
        if any(module.startswith(f"factory_simulator.{name}") for name in forbidden)
    ]

    assert wrong == []


@pytest.mark.parametrize(
    ("source", "package", "imported"),
    [
        (
            "import factory_simulator.api",
            "factory_simulator.engine",
            ["factory_simulator.api"],
        ),
        (
            "from .. import steps",
            "factory_simulator.engine.rules",
            ["factory_simulator.engine.steps"],
        ),
        (
            "from ...api.core import numbers",
            "factory_simulator.engine.rules",
            ["factory_simulator.api.core"],
        ),
        (
            "from factory_simulator.engine import check_factory",
            "factory_simulator.api",
            ["factory_simulator.engine"],
        ),
    ],
)
def test_the_reader_finds_every_form_of_import(
    source: str, package: str, imported: list[str]
):
    assert imported_modules(source, package) == imported

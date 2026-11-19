from factories import document_paths, map_paths, schema_paths
from pydantic import BaseModel

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.schemas.manifest import ManifestCreate
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.examples import EXAMPLES

TEMPLATES = EXAMPLES / "templates"


def missing_paths(model: type[BaseModel], name: str) -> list[str]:
    paths = schema_paths(model.model_json_schema())
    template = read_json_bytes((TEMPLATES / name).read_bytes())
    return sorted(paths - document_paths(template, map_paths(paths)))


def test_every_path_of_the_manifest_schema_is_in_the_template():
    assert missing_paths(ManifestCreate, "manifest.json") == []


def test_every_path_of_the_scenario_schema_is_in_the_template():
    assert missing_paths(ScenarioCreate, "scenario.json") == []

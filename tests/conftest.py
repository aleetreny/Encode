import json

import pytest
from fastapi.testclient import TestClient

from backend.config import ROOT, Settings
from backend.main import create_app
from backend.models import Scenario


@pytest.fixture
def scenario_json():
    return json.loads((ROOT / "data/demo/chile-demo-001.scenario.json").read_text())


@pytest.fixture
def scenario(scenario_json):
    return Scenario.model_validate(scenario_json)


@pytest.fixture
def replay():
    return json.loads((ROOT / "data/demo/chile-demo-001.replay.json").read_text())


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "runs.sqlite3")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client

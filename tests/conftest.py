import importlib.util
from pathlib import Path

import pytest

from assistant.db import get_readonly_connection

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_db.py"
SEED = 42


@pytest.fixture(scope="session")
def build_db_module():
    spec = importlib.util.spec_from_file_location("build_db", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def built_db(build_db_module, tmp_path_factory):
    """A fresh DB built into a temp dir, so tests never touch data/suppliers.db."""
    path = tmp_path_factory.mktemp("db") / "suppliers.db"
    build_db_module.build(path, SEED)
    return path


@pytest.fixture
def conn(built_db):
    connection = get_readonly_connection(built_db)
    yield connection
    connection.close()

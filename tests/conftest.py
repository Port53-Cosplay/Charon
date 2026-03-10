"""Test configuration — isolate tests from the real database."""

import tempfile
from pathlib import Path

import pytest

import charon.db as db_module


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path):
    """Redirect all DB operations to a temporary database for every test."""
    original_path = db_module.DB_PATH
    test_db = tmp_path / "test_charon.db"
    db_module.DB_PATH = test_db
    db_module.init_db()
    yield
    db_module.DB_PATH = original_path

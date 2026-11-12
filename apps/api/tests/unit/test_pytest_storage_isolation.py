"""Pytest must configure storage before any test imports the application."""
from config import DB_BACKEND, DB_PATH, FILE_STORAGE_PATH


def test_application_configuration_uses_session_temporary_storage():
    assert DB_BACKEND == 'sqlite'
    assert DB_PATH.parent.name.startswith('team18-pytest-')
    assert FILE_STORAGE_PATH.parent == DB_PATH.parent

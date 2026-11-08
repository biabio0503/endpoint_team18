"""Offline pdf source adapter; its fixture origin is not a real service."""
from .fixture_source import collect as collect_fixture

def collect(scope):
    return collect_fixture('fixture-pdf',scope)

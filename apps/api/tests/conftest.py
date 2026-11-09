"""Legacy behavior scenarios intentionally issue many rapid mocked AI requests.

The guard's dedicated tests set small explicit limits and exercise real concurrent
reservations; other tests suppress only time/volume limits, never ownership/leases.
"""
import pytest

@pytest.fixture(autouse=True)
def isolated_mock_budget(monkeypatch):
    for key, value in {'COOLDOWN_SECONDS': '0', 'GUEST_HOURLY_UNITS': '100000',
                       'GUEST_DAILY_UNITS': '100000', 'USER_HOURLY_UNITS': '100000',
                       'USER_DAILY_UNITS': '100000', 'GLOBAL_DAILY_UNITS': '100000'}.items():
        monkeypatch.setenv('ROADMAP_AI_' + key, value)

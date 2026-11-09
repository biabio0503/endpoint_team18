import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

import pytest
from api.dependencies import get_context
from api.domain import Problem


class DB:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return {'owner_id': 'stored-owner'}


class Response(io.BytesIO):
    pass


def request(auth=None):
    return SimpleNamespace(headers={'authorization': auth} if auth else {}, cookies={'roadmap_session': 'x' * 43})


def test_missing_token_does_not_use_legacy_cookie():
    db = DB()
    with patch('api.dependencies.DB_BACKEND', 'postgres'):
        assert get_context(request(), db)[2] is None
    assert db.calls == []


def test_verified_user_is_the_only_identity_used(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    db = DB()
    user_id = '7c050641-7bda-4988-aea0-2e210731682b'
    with patch('api.dependencies.DB_BACKEND', 'postgres'), patch('api.dependencies.urlopen', return_value=Response(json.dumps({'id': user_id}).encode())):
        assert get_context(request('Bearer valid.jwt.token'), db)[2] == {'owner_id': 'stored-owner', 'is_anonymous': True}
    assert db.calls[0][1][-1] == user_id
    assert db.calls[1][1] == (user_id,)


def test_invalid_token_cannot_create_owner(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    db = DB()
    error = HTTPError('https://example.supabase.co', 401, 'unauthorized', {}, None)
    with patch('api.dependencies.DB_BACKEND', 'postgres'), patch('api.dependencies.urlopen', side_effect=error), pytest.raises(Problem) as raised:
        get_context(request('Bearer invalid'), db)
    assert raised.value.status == 401
    assert db.calls == []

@pytest.mark.parametrize('anonymous', [True, False])
def test_guest_budget_identity_ignores_editable_metadata(monkeypatch, anonymous):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    user = {'id':'7c050641-7bda-4988-aea0-2e210731682b', 'is_anonymous':anonymous,
            'user_metadata':{'is_anonymous':not anonymous}}
    with patch('api.dependencies.DB_BACKEND','postgres'), patch('api.dependencies.urlopen',return_value=Response(json.dumps(user).encode())):
        assert get_context(request('Bearer verified.jwt'),DB())[2]['is_anonymous'] is anonymous

"""Storage contract tests without cloud credentials or network access."""
import sys
import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from providers.document_storage import SupabaseDocumentStorage

KEY = '12345678-1234-4234-8234-123456789abc'


def storage():
    return SupabaseDocumentStorage('https://example.supabase.co', 'sb_secret_test', 'private-bucket')


def test_upload_requires_private_bucket_and_disallows_overwrite():
    client = storage()
    with patch.object(client, '_request', side_effect=[b'{"public": false}', b'{}']) as request:
        client.save(KEY, b'hello', 'text/plain')
    assert request.call_args_list[1].args == (
        'POST', '/object/private-bucket/' + KEY, b'hello',
        {'Content-Type': 'text/plain', 'x-upsert': 'false'})
    with patch.object(client, '_request', return_value=b'{"public": true}') as request:
        with pytest.raises(OSError):
            client.save(KEY, b'hello')
        assert request.call_count == 1


def test_read_and_delete_use_only_the_exact_validated_key():
    client = storage()
    with patch.object(client, '_request', side_effect=[b'{"public": false}', b'content', b'{"public": false}', b'[]', b'{"public": false}', None]) as request:
        assert client.read(KEY) == b'content'
        client.delete(KEY)
    assert request.call_args_list[1].args[1] == '/object/private-bucket/' + KEY
    assert request.call_args_list[3].args[2] == ('{"prefixes": ["' + KEY + '"]}').encode()
    for invalid in ('../' + KEY, KEY.upper(), KEY + '/other', 'not-a-uuid'):
        with pytest.raises(ValueError):
            client.delete(invalid)


def test_requires_https_and_nonempty_server_key():
    with pytest.raises(ValueError):
        SupabaseDocumentStorage('http://example.com', 'secret')
    with pytest.raises(ValueError):
        SupabaseDocumentStorage('https://example.com', '')


def jwt_key(role):
    payload = base64.urlsafe_b64encode(json.dumps({'role': role}).encode()).decode().rstrip('=')
    return 'eyJhbGciOiJIUzI1NiJ9.' + payload + '.test-signature'


@pytest.mark.parametrize('key, bearer', [('sb_secret_test', False), (jwt_key('service_role'), True)])
def test_server_key_headers_match_authentication_type(key, bearer):
    client = SupabaseDocumentStorage('https://example.supabase.co', key)
    with patch('providers.document_storage.build_opener') as opener:
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
        client._request('GET', '/bucket/roadmap-documents')
        request = opener.return_value.open.call_args.args[0]
    assert request.get_header('Apikey') == key
    assert request.get_header('Authorization') == ('Bearer ' + key if bearer else None)


@pytest.mark.parametrize('key', ['sb_publishable_test', jwt_key('anon'), 'invalid-key'])
def test_public_or_invalid_keys_are_rejected_without_exposing_them(key):
    with pytest.raises(ValueError) as error:
        SupabaseDocumentStorage('https://example.supabase.co', key)
    assert key not in str(error.value)


def test_ambiguous_key_configuration_fails_closed(monkeypatch):
    import config
    from providers.document_storage import get_storage
    from repositories.postgres import StorageUnavailable
    monkeypatch.setattr(config, 'DB_BACKEND', 'postgres')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'sb_secret_test')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', jwt_key('service_role'))
    with pytest.raises(StorageUnavailable):
        get_storage()

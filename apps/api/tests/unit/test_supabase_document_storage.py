"""Storage contract tests without cloud credentials or network access."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from providers.document_storage import SupabaseDocumentStorage

KEY = '12345678-1234-4234-8234-123456789abc'


def storage():
    return SupabaseDocumentStorage('https://example.supabase.co', 'secret', 'private-bucket')


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

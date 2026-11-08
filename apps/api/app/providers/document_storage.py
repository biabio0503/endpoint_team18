"""Private filesystem storage. Keys are server-generated document UUIDs only."""
import os
from pathlib import Path
import re
import json
import base64
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from config import FILE_STORAGE_PATH

class LocalDocumentStorage:
    def __init__(self, root=FILE_STORAGE_PATH): self.root=Path(root)
    def path(self,key):
        if not re.fullmatch(r'[0-9a-f-]{36}',key): raise ValueError('invalid storage key')
        return self.root/key
    def save(self,key,data):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path(key),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        except BaseException:
            self.delete(key)
            raise
    def read(self,key): return self.path(key).read_bytes()
    def delete(self,key): self.path(key).unlink(missing_ok=True)
    def old_keys(self, cutoff):
        if not self.root.exists(): return []
        return [path.name for path in self.root.iterdir() if re.fullmatch(r'[0-9a-f-]{36}',path.name) and path.is_file() and path.stat().st_mtime<cutoff]


class SupabaseDocumentStorage:
    """Server-only Storage REST client. Never returns public or signed URLs."""
    def __init__(self, url, secret, bucket='roadmap-documents'):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('invalid Supabase URL')
        if not secret or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', bucket):
            raise ValueError('invalid Supabase storage configuration')
        self.url = url.rstrip('/') + '/storage/v1'
        self.secret = secret
        self.bucket = bucket
        self._auth_headers()  # Reject public keys and malformed credentials early.

    def _auth_headers(self):
        if self.secret.startswith('sb_secret_') and len(self.secret) > len('sb_secret_'):
            # New opaque keys are API keys, not bearer JWTs.
            return {'apikey': self.secret}
        try:
            parts = self.secret.split('.')
            if len(parts) != 3 or not all(parts):
                raise ValueError
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
            if payload.get('role') != 'service_role':
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError('a server-only Supabase key is required') from None
        # This checks configuration shape only; Supabase verifies the signature.
        return {'apikey': self.secret, 'Authorization': 'Bearer ' + self.secret}

    @staticmethod
    def _key(key):
        # Canonical UUIDs only: callers cannot choose paths or other objects.
        import uuid
        try:
            if str(uuid.UUID(key)) != key:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError('invalid storage key') from None
        return key

    def _request(self, method, path, data=None, headers=None, missing_ok=False):
        request = Request(self.url + path, data=data, method=method, headers={
            **self._auth_headers(), **(headers or {})})
        try:
            # Never forward credentials to a redirect target.
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                return response.read()
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            if missing_ok and error.code == 400:
                try:
                    body = json.loads(error.read())
                    if str(body.get('statusCode')) == '404':
                        return None
                except (ValueError, TypeError, AttributeError):
                    pass
            raise OSError('Supabase Storage request failed') from None
        except (URLError, TimeoutError, OSError):
            raise OSError('Supabase Storage request failed') from None

    def _private_bucket(self):
        raw = self._request('GET', '/bucket/' + quote(self.bucket, safe=''))
        try:
            bucket = json.loads(raw)
            if bucket.get('public') is not False:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise OSError('Supabase Storage bucket is not private') from None

    def save(self, key, data, mime_type='application/octet-stream'):
        key = self._key(key)
        self._private_bucket()
        self._request('POST', '/object/' + quote(self.bucket, safe='') + '/' + key,
                      data, {'Content-Type': mime_type, 'x-upsert': 'false'})

    def read(self, key):
        key = self._key(key)
        self._private_bucket()
        result = self._request('GET', '/object/' + quote(self.bucket, safe='') + '/' + key)
        return result

    def exists(self, key):
        key = self._key(key)
        self._private_bucket()
        # The metadata endpoint has a JSON error body; HEAD can report a
        # bodyless 400 for both missing files and other failures.
        return self._request('GET', '/object/info/' + quote(self.bucket, safe='') + '/' + key, missing_ok=True) is not None

    def delete(self, key):
        key = self._key(key)
        self._private_bucket()
        body = json.dumps({'prefixes': [key]}).encode()
        self._request('DELETE', '/object/' + quote(self.bucket, safe=''), body,
                      {'Content-Type': 'application/json'})
        if self.exists(key):
            raise OSError('Supabase Storage object was not deleted')


def get_storage():
    from config import DB_BACKEND
    if DB_BACKEND == 'postgres':
        from repositories.postgres import StorageUnavailable
        try:
            if os.environ.get('SUPABASE_SECRET_KEY') and os.environ.get('SUPABASE_SERVICE_ROLE_KEY'):
                raise ValueError('configure only one server key')
            return SupabaseDocumentStorage(os.environ.get('SUPABASE_URL', ''),
                os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''),
                os.environ.get('SUPABASE_STORAGE_BUCKET', 'roadmap-documents'))
        except ValueError:
            raise StorageUnavailable('Supabase Storage 설정을 확인해 주세요.') from None
    return LocalDocumentStorage()

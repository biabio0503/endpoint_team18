"""Synthetic Auth service for the opt-in disposable PostgreSQL tests only."""
from contextlib import closing
from io import BytesIO
import json
from unittest.mock import patch
import uuid


class PostgresTestAuth:
    def __init__(self):
        self.users = set()
        self.environment = patch.dict('os.environ', {'SUPABASE_URL': 'https://synthetic-auth.invalid', 'SUPABASE_PUBLISHABLE_KEY': 'test'})
        self.http = patch('api.dependencies.urlopen', side_effect=self.lookup)

    def start(self):
        self.environment.start()
        self.http.start()
        return self

    def stop(self):
        self.http.stop()
        self.environment.stop()

    def headers(self):
        from repositories.plans import connect
        user = str(uuid.uuid4())
        with closing(connect()) as db:
            db.execute('INSERT INTO auth.users(id) VALUES(?)', (user,))
        self.users.add(user)
        return {'Authorization': 'Bearer ' + user}

    def lookup(self, request, **kwargs):
        user = request.get_header('Authorization').removeprefix('Bearer ')
        assert user in self.users
        return BytesIO(json.dumps({'id': user}).encode())

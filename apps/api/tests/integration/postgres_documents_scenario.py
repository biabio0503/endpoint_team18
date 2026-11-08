"""Run only against a disposable local database called team18_document_test."""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import secrets
import sys
import uuid
from urllib.parse import urlsplit

import psycopg

url = os.environ['ROADMAP_TEST_POSTGRES_URL']
parsed = urlsplit(url)
assert parsed.hostname in ('127.0.0.1', 'localhost') and parsed.path == '/team18_document_test'
app_root = Path(__file__).resolve().parents[2]
root = app_root.parents[1]
with psycopg.connect(url, autocommit=True) as db:
    db.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
    db.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
    END $$""")
    db.execute('''CREATE TABLE session_owners (owner_id text primary key, token_digest text unique not null,
      expires_at timestamptz not null, created_at timestamptz not null);
      CREATE TABLE roadmap_inputs (request_id text primary key, owner_id text not null references session_owners,
      input_revision integer not null default 0, created_at timestamptz not null, updated_at timestamptz not null)''')
    for sql in sorted((root / 'supabase/migrations').glob('*documents.sql')):
        db.execute(sql.read_text())
    for sql in sorted((root / 'supabase/migrations').glob('*document_upload_reservations.sql')):
        db.execute(sql.read_text())
    assert db.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.project_documents'::regclass").fetchone()[0]
    assert not db.execute("SELECT has_table_privilege('anon','public.project_documents','select')").fetchone()[0]

os.environ.update(ROADMAP_DB_BACKEND='postgres', ROADMAP_DATABASE_URL=url,
                  ROADMAP_POSTGRES_DOCUMENTS_ENABLED='1', ROADMAP_INSECURE_LOCAL_COOKIE='1',
                  ROADMAP_APP_ORIGIN='http://localhost:3000')
sys.path.insert(0, str(app_root / 'app'))
sys.path.insert(0, str(app_root))
from fastapi.testclient import TestClient
from app.main import app
from api.routes import documents as routes
from worker import documents as worker

class FakeStorage:
    def __init__(self): self.files = {}; self.fail = False
    def save(self, key, data, mime):
        assert key not in self.files
        self.files[key] = data
        if self.fail: raise OSError('simulated ambiguous upload')
    def read(self, key): return self.files[key]
    def delete(self, key): self.files.pop(key, None)

store = FakeStorage()
routes.get_storage = lambda: store
worker.get_storage = lambda: store
# Explicitly drive durable jobs so response assertions are deterministic.
routes.request_work = lambda: None
token = secrets.token_urlsafe(32)
owner = str(uuid.uuid4()); rid = str(uuid.uuid4())
with psycopg.connect(url, autocommit=True) as db:
    db.execute("INSERT INTO session_owners VALUES (%s,%s,now()+interval '1 day',now())", (owner, hashlib.sha256(token.encode()).hexdigest()))
    db.execute('INSERT INTO roadmap_inputs VALUES (%s,%s,0,now(),now())', (rid, owner))

origin = {'Origin': 'http://localhost:3000'}
path = '/api/roadmap-inputs/' + rid + '/documents'
def upload(client, revision, content=b'hello'):
    return client.post(path, headers=origin, data={'expected_input_revision':str(revision)}, files={'file':('test.txt', content, 'text/plain')})

with TestClient(app, raise_server_exceptions=False) as client:
    client.cookies.set('roadmap_session', token)
    assert client.post(path, files={'file':('x.txt',b'x')}, data={'expected_input_revision':'0'}).status_code == 403
    assert client.get(path.replace(rid, str(uuid.uuid4()))).status_code == 404
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(client, 0), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409], [(r.status_code,r.text) for r in responses]
    did = next(r.json()['document']['document_id'] for r in responses if r.status_code == 201)
    assert worker.run_once(store)
    listing = client.get(path).json()
    assert listing['input_revision'] == 2 and listing['documents'][0]['extraction_status'] == 'ready'
    extraction = client.get(f'{path}/{did}/extractions/1')
    assert extraction.status_code == 200 and extraction.json()['segments'][0]['paragraph'] == 1
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("UPDATE project_documents SET extraction_status='partial' WHERE document_id=%s", (did,))
        db.execute("UPDATE document_extractions SET extraction_status='partial' WHERE document_id=%s", (did,))
    confirm = client.post(f'{path}/{did}/extractions/1/confirmation', headers=origin, json={'expected_input_revision':2})
    assert confirm.status_code == 200 and confirm.json()['analysis_eligible']
    retry = client.post(f'{path}/{did}/retry-extraction', headers=origin, json={'expected_input_revision':3})
    assert retry.status_code == 202 and worker.run_once(store)
    assert client.get(f'{path}/{did}/extractions/1').json()['is_current_revision'] is False
    deleted = client.request('DELETE', f'{path}/{did}', headers=origin, json={'expected_input_revision':5})
    assert deleted.status_code == 200 and worker.run_once(store)
    assert did not in store.files
    assert client.get(f'{path}/{did}/extractions/2').status_code == 410
    store.fail = True
    failed = upload(client, 6)
    assert failed.status_code == 503, failed.text
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("UPDATE document_upload_reservations SET expires_at=now()-interval '1 minute' WHERE committed_at IS NULL")
    store.fail = False
    while worker.cleanup_reservation(store): pass
    assert not store.files
    with psycopg.connect(url, autocommit=True) as db:
        assert db.execute('SELECT count(*) FROM document_upload_reservations WHERE cleanup_lease_until > now()').fetchone()[0] >= 1
        late_key = db.execute('SELECT storage_key FROM document_upload_reservations WHERE committed_at IS NULL LIMIT 1').fetchone()[0]
        db.execute("UPDATE document_upload_reservations SET cleanup_lease_until=now()-interval '1 minute' WHERE storage_key=%s", (late_key,))
    store.files[late_key] = b'late object'
    assert worker.cleanup_reservation(store) and late_key not in store.files
    new = upload(client, 6)
    assert new.status_code == 201
    new_id = new.json()['document']['document_id']
    first = worker.claim()
    assert first and first[0]['document_id'] == new_id
    assert worker.claim() is None
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("UPDATE project_documents SET extraction_lease_until=now()-interval '1 second' WHERE document_id=%s", (new_id,))
    second = worker.claim()
    assert second and second[1] != first[1]
    removed = client.request('DELETE', f'{path}/{new_id}', headers=origin, json={'expected_input_revision':7})
    assert removed.status_code == 200
    from contextlib import closing
    from repositories.documents import DocumentRepository
    with closing(worker.connect()) as db:
        db.execute('BEGIN')
        DocumentRepository(db).finish_extraction(first[0], first[1],
            {'text':'stale','segments':[],'limitations':[],'status':'ready','error_code':None}, worker.timestamp())
        DocumentRepository(db).finish_extraction(second[0], second[1],
            {'text':'stale','segments':[],'limitations':[],'status':'ready','error_code':None}, worker.timestamp())
        db.commit()
    with psycopg.connect(url) as db:
        assert db.execute('SELECT extraction_status FROM project_documents WHERE document_id=%s', (new_id,)).fetchone()[0] == 'pending'
    assert worker.run_once(store)
    routes.request_work = worker.request_work
    for filename in ('project-ready.pdf', 'project-ready.docx', 'project-ready.txt'):
        current = client.get(path).json()['input_revision']
        content = (root / 'docs/test-files' / filename).read_bytes()
        response = client.post(path, headers=origin, data={'expected_input_revision':str(current)},
                               files={'file':(filename,content)})
        assert response.status_code == 201, (filename, response.text)
        created = response.json()['document']['document_id']
        listing = client.get(path).json()
        found = next(d for d in listing['documents'] if d['document_id'] == created)
        assert found['extraction_status'] in ('ready', 'partial'), (filename, found)
        assert client.get(f"{path}/{created}/extractions/1").status_code == 200
    from unittest.mock import patch
    from repositories.postgres import StorageUnavailable
    current = client.get(path).json()['input_revision']
    existing_keys = set(store.files)
    with patch.object(routes.DocumentRepository, 'create', side_effect=StorageUnavailable('test failure')):
        response = upload(client, current)
    assert response.status_code == 503
    orphan_keys = set(store.files) - existing_keys
    assert len(orphan_keys) == 1
    orphan = next(iter(orphan_keys))
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("UPDATE document_upload_reservations SET expires_at=now()-interval '1 minute' WHERE storage_key=%s", (orphan,))
    assert worker.cleanup_reservation(store) and orphan not in store.files
    assert existing_keys == set(store.files)

with TestClient(app) as stranger:
    assert stranger.get(path).status_code == 401
    other_token = secrets.token_urlsafe(32)
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("INSERT INTO session_owners VALUES (%s,%s,now()+interval '1 day',now())", (str(uuid.uuid4()), hashlib.sha256(other_token.encode()).hexdigest()))
    stranger.cookies.set('roadmap_session', other_token)
    assert stranger.get(path).status_code == 404
    assert stranger.get(f'{path}/{did}/extractions/1').status_code == 404

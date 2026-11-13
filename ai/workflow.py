"""Local CLI workflow; no web server required."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from intake import create

ROOT = Path(__file__).resolve().parent.parent

def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def open_db(storage):
    db = sqlite3.connect(Path(storage) / 'intake.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS reviews (request_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, source_hash TEXT NOT NULL, provider TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL)')
    return db
def get_input(db, rid):
    row = db.execute('SELECT input_json FROM requests WHERE request_id=?', (rid,)).fetchone()
    if not row: raise ValueError('요청을 찾을 수 없습니다.')
    return json.loads(row[0])
def run_model(data, provider):
    env = os.environ.copy(); env['AI_PROVIDER'] = provider
    env.setdefault('AI_PYTHON', sys.executable)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', delete=False) as f:
        json.dump(data, f, ensure_ascii=False); path = f.name
    try:
        command = ['node']
        if (ROOT / 'ai' / '.env').exists(): command.append('--env-file=ai/.env')
        command += ['ai/generate.mjs', path]
        p = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=200)
        if p.returncode: raise ValueError(p.stderr.strip() or 'AI 실행 실패')
        return json.loads(p.stdout)
    finally: Path(path).unlink(missing_ok=True)
def analyze(db, rid, provider):
    data = get_input(db, rid)
    source = digest(data)
    review_row = db.execute('SELECT source_hash,data FROM reviews WHERE request_id=?', (rid,)).fetchone()
    if review_row and review_row[0] == source: data['user_review'] = json.loads(review_row[1])
    result = run_model(data, provider)
    review_hash = digest(data.get('user_review'))
    # Confirm neither inputs nor review changed while the model was running.
    current = get_input(db, rid)
    current_review = db.execute('SELECT source_hash,data FROM reviews WHERE request_id=?', (rid,)).fetchone()
    current_review_data = json.loads(current_review[1]) if current_review and current_review[0] == digest(current) else None
    if digest(current) != source or digest(current_review_data) != review_hash: raise ValueError('분석 중 입력이 바뀌어 결과를 저장하지 않았습니다.')
    snapshot = digest({'input': current, 'review': current_review_data})
    db.execute('INSERT INTO results(request_id,source_hash,provider,result,created_at) VALUES(?,?,?,?,?)', (rid, snapshot, provider, canonical(result), datetime.now(timezone.utc).isoformat()))
    db.commit()
    return result
def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest='action', required=True)
    c = sub.add_parser('create'); c.add_argument('input'); c.add_argument('--storage', required=True); c.add_argument('--ocr', action='store_true'); c.add_argument('--ocr-model', choices=['local','open-source'], default='local')
    for name in ('analyze', 'review', 'status'):
        cmd = sub.add_parser(name); cmd.add_argument('request_id'); cmd.add_argument('--storage', required=True)
        if name == 'analyze': cmd.add_argument('--provider', choices=['gemini', 'local'], default='gemini')
        if name == 'review': cmd.add_argument('file')
    args = p.parse_args()
    if args.action == 'create':
        with contextlib.redirect_stdout(io.StringIO()) as output: create(args.input, args.storage, args.ocr, args.ocr_model)
        data = json.loads(output.getvalue()); print(json.dumps(data, ensure_ascii=False, indent=2)); return
    with contextlib.closing(open_db(args.storage)) as db:
        data = get_input(db, args.request_id)
        if args.action == 'analyze': result = analyze(db, args.request_id, args.provider)
        elif args.action == 'review':
            review = json.loads(Path(args.file).read_text(encoding='utf-8-sig'))
            if not isinstance(review, dict) or not isinstance(review.get('confirmed_experiences'), list) or not isinstance(review.get('answers'), list): raise ValueError('confirmed_experiences와 answers 배열이 필요합니다.')
            db.execute('INSERT OR REPLACE INTO reviews VALUES(?,?,?)', (args.request_id, digest(data), canonical(review))); db.commit()
            result = {'saved': True, 'message': '확인 내용 저장됨. 다시 analyze를 실행하세요.'}
        else:
            review = db.execute('SELECT source_hash,data FROM reviews WHERE request_id=?', (args.request_id,)).fetchone()
            reviewed = json.loads(review[1]) if review and review[0] == digest(data) else None
            row = db.execute('SELECT source_hash,provider,result,created_at FROM results WHERE request_id=? ORDER BY id DESC LIMIT 1', (args.request_id,)).fetchone()
            result = {'found': bool(row), 'review_current': reviewed is not None, 'stale': bool(row and row[0] != digest({'input': data, 'review': reviewed})), 'provider': row[1] if row else None, 'result': json.loads(row[2]) if row else None, 'created_at': row[3] if row else None}
        print(json.dumps(result, ensure_ascii=False, indent=2))
if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as e: print(str(e), file=sys.stderr); sys.exit(1)

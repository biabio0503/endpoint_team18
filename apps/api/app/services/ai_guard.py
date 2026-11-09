"""Durable, atomic budgets across plans/processes. Cached reads consume no budget.

Units are conservative upper bounds on provider calls, including SDK retries.
Global daily limits also bound account-rotation abuse. Auth CAPTCHA is complementary.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from api.domain import Problem
from repositories.experience_analysis import decode


def setting(name, default):
    return max(0, int(os.environ.get('ROADMAP_AI_' + name, default)))


def guarded_call(ctx, operation, basis_hash, call, *, units=1, cache=False):
    db, _, owner = ctx
    owner_id = owner['owner_id']
    postgres = getattr(db, 'backend', 'sqlite') == 'postgres'
    at = datetime.now(timezone.utc)
    db.execute('BEGIN' if postgres else 'BEGIN IMMEDIATE')
    try:
        if postgres:
            # All workers share this brief reservation lock; never held during I/O.
            db.execute('SELECT pg_advisory_xact_lock(18180733)')
        if cache:
            saved = db.execute("""SELECT result_json FROM ai_requests WHERE owner_id=? AND operation=?
                AND basis_hash=? AND status='finished' AND result_json IS NOT NULL
                ORDER BY created_at DESC LIMIT 1""", (owner_id, operation, basis_hash)).fetchone()
            if saved:
                db.commit()
                return decode(saved['result_json'])
        if db.execute("SELECT 1 FROM ai_requests WHERE owner_id=? AND status='running' AND lease_until>?",
                      (owner_id, at.isoformat())).fetchone():
            raise Problem(409, 'ai_request_in_progress', '다른 분석 요청을 처리 중입니다. 완료 후 저장 결과를 확인해 주세요.')
        if db.execute('SELECT 1 FROM ai_requests WHERE owner_id=? AND operation=? AND created_at>?',
                      (owner_id, operation, (at - timedelta(seconds=setting('COOLDOWN_SECONDS', 60))).isoformat())).fetchone():
            raise Problem(429, 'ai_cooldown', '같은 분석은 잠시 기다린 뒤 다시 실행해 주세요. 저장 결과는 계속 조회할 수 있습니다.')
        # Use verified /auth/v1/user identity, never editable user_metadata.
        guest = dict(owner).get('is_anonymous', True)
        limits = [(True, 1, setting('GUEST_HOURLY_UNITS' if guest else 'USER_HOURLY_UNITS', 60 if guest else 120)),
                  (True, 24, setting('GUEST_DAILY_UNITS' if guest else 'USER_DAILY_UNITS', 120 if guest else 360)),
                  (False, 24, setting('GLOBAL_DAILY_UNITS', 600))]
        for personal, hours, limit in limits:
            sql = 'SELECT COALESCE(SUM(units),0) AS used FROM ai_requests WHERE created_at>?'
            params = [(at - timedelta(hours=hours)).isoformat()]
            if personal:
                sql += ' AND owner_id=?'
                params.append(owner_id)
            if db.execute(sql, params).fetchone()['used'] + units > limit:
                raise Problem(429, 'ai_budget_exceeded', '분석 사용량 한도에 도달했습니다. 저장 결과나 제한 안내 로드맵을 이용해 주세요.')
        request_id = str(uuid.uuid4())
        db.execute("""INSERT INTO ai_requests(request_id,owner_id,operation,basis_hash,units,status,created_at,lease_until)
            VALUES(?,?,?,?,?,'running',?,?)""", (request_id, owner_id, operation, basis_hash, units,
              at.isoformat(), (at + timedelta(minutes=30)).isoformat()))
        db.commit()
    except Exception:
        db.execute('ROLLBACK')
        raise
    try:
        result = call()
    except Exception:
        db.execute("UPDATE ai_requests SET status='failed' WHERE request_id=?", (request_id,))
        db.commit()
        raise
    db.execute("UPDATE ai_requests SET status='finished',result_json=? WHERE request_id=?",
               (json.dumps(result, ensure_ascii=False, default=str) if cache else None, request_id))
    db.commit()
    return result

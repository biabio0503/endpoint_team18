"""Durable at-most-once OCR attempts, independent of Gemini's budgets.

The immutable document and unit key survive extraction revisions. A reservation
is never refunded, even if a crash happened before dispatch. This deliberately
prefers an unread area to a possibly duplicated billable request.
"""
from contextlib import closing
from datetime import datetime, timezone
import json

from config import ocr_settings
from providers.google_vision_ocr import GoogleVisionOCR, OCRError, availability
from repositories.plans import connect
from services.ocr_billing import billing_period


class LeaseLost(Exception):
    pass


def now():
    return datetime.now(timezone.utc)


def budget_time(db):
    """All PostgreSQL workers use the same clock, independent of host timezones/skew."""
    if getattr(db, 'backend', 'sqlite') == 'postgres':
        return db.execute('SELECT clock_timestamp() AS at').fetchone()['at'].astimezone(timezone.utc)
    return now()


def remaining(db, *, period=None):
    period = period or billing_period(budget_time(db))
    used = db.execute('SELECT count(*) AS n FROM document_ocr_units WHERE billing_period=?',
                      (period,)).fetchone()['n']
    return max(0, ocr_settings()['monthly_limit'] - used)


def policy(db):
    reason = availability()
    if reason is None and remaining(db) == 0:
        reason = 'ocr_budget_exceeded'
    if reason is None and ocr_settings()['document_limit'] == 0:
        reason = 'ocr_document_limit'
    return {'enabled': ocr_settings()['provider'] == 'google_vision',
            'available': reason is None, 'reason': reason}


def retry_policy(doc, ocr_policy, db=None):
    status = doc['extraction_status']; error = doc['extraction_error_code']
    if status == 'pending':
        return {'retry_available': False, 'retry_reason': 'already_pending'}
    if error == 'ocr_document_limit' and db is not None:
        used = db.execute('SELECT count(*) AS n FROM document_ocr_units WHERE document_id=?',
                          (doc['document_id'],)).fetchone()['n']
        if used < ocr_settings()['document_limit']:
            return {'retry_available': ocr_policy['available'], 'retry_reason': ocr_policy['reason']}
    terminal = {'ocr_timeout', 'ocr_uncertain', 'ocr_api_error', 'ocr_auth_error',
                'ocr_quota_exceeded', 'ocr_result_too_large', 'ocr_document_limit', 'ocr_empty_text'}
    if error in terminal:
        return {'retry_available': False, 'retry_reason': error}
    if status == 'needs_ocr' or (error and error.startswith('ocr_')):
        return {'retry_available': ocr_policy['available'], 'retry_reason': ocr_policy['reason']}
    return {'retry_available': True, 'retry_reason': None}


class DocumentOCR:
    def __init__(self, row, token, check, provider=None):
        self.row = row
        self.token = token
        self.check = check
        self.provider = provider or GoogleVisionOCR()
        self.injected = provider is not None

    def _active(self, db):
        sql = 'SELECT * FROM project_documents WHERE document_id=?'
        if getattr(db, 'backend', 'sqlite') == 'postgres': sql += ' FOR UPDATE'
        current = db.execute(sql, (self.row['document_id'],)).fetchone()
        if (not current or current['removed_at'] is not None
                or current['extraction_revision'] != self.row['extraction_revision']
                or current['extraction_status'] != 'pending'
                or current['extraction_lease_token'] != self.token
                or not current['extraction_lease_until']):
            raise LeaseLost()
        until = current['extraction_lease_until']
        if isinstance(until, str): until = datetime.fromisoformat(until)
        if until <= now(): raise LeaseLost()

    def _lookup(self, db, key):
        return db.execute('SELECT * FROM document_ocr_units WHERE document_id=? AND unit_key=?',
                          (self.row['document_id'], key)).fetchone()

    @staticmethod
    def _reuse(saved):
        if saved['status'] == 'completed' and saved['result_json']:
            return json.loads(saved['result_json'])
        raise OCRError(saved['error_code'] or 'ocr_uncertain')

    def read(self, key, make_image):
        self.check()
        if not self.injected and ocr_settings()['provider'] != 'google_vision':
            raise OCRError('ocr_disabled')
        try:
            return self._read(key, make_image)
        except (OCRError, LeaseLost):
            raise
        except Exception:
            # DB failures never authorize a call, and never discard native text.
            raise OCRError('ocr_storage_error') from None

    def _read(self, key, make_image):
        with closing(connect()) as db:
            saved = self._lookup(db, key)
            if saved: return self._reuse(saved)
        reason = None if self.injected else availability()
        if reason: raise OCRError(reason)
        content = make_image()
        if content is None: return {'text': '', 'segments': [], 'blank': True}
        self.check()
        with closing(connect()) as db:
            postgres = getattr(db, 'backend', 'sqlite') == 'postgres'
            # A session default of REPEATABLE READ would retain the snapshot
            # taken by _active() before waiting for the global lock. Explicit
            # READ COMMITTED ensures the count sees the previous holder's commit.
            db.execute('BEGIN ISOLATION LEVEL READ COMMITTED' if postgres else 'BEGIN IMMEDIATE')
            self._active(db)
            if postgres:
                # Dedicated lock shared by every process, across all owners.
                db.execute('SELECT pg_advisory_xact_lock(18180734)')
            saved = self._lookup(db, key)
            if saved:
                db.commit()
                return self._reuse(saved)
            count = db.execute('SELECT count(*) AS n FROM document_ocr_units WHERE document_id=?',
                               (self.row['document_id'],)).fetchone()['n']
            if count >= ocr_settings()['document_limit']: raise OCRError('ocr_document_limit')
            at = budget_time(db).astimezone(timezone.utc)
            period = billing_period(at)
            if remaining(db, period=period) < 1: raise OCRError('ocr_budget_exceeded')
            db.execute("""INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
                usage_month,billing_period,status,created_at) VALUES(?,?,?,?,?,'reserved',?)""",
                (self.row['document_id'], key, self.row['extraction_revision'],
                 at.strftime('%Y-%m'), period, at.isoformat()))
            db.commit()  # Must be durable before dispatch. Never refund uncertain calls.
        self.check()
        with closing(connect()) as db:
            dispatch_period = billing_period(budget_time(db))
        if dispatch_period != period:
            # A delayed dispatch must not spend a previous month's reservation.
            raise OCRError('ocr_uncertain')
        try:
            result = self.provider.detect(content)
        except OCRError as error:
            self._save(key, None, error.code)
            raise
        except Exception:
            self._save(key, None, 'ocr_uncertain')
            raise OCRError('ocr_uncertain') from None
        self._save(key, result, None)
        self.check()
        return result

    def _save(self, key, result, error):
        with closing(connect()) as db:
            db.execute('BEGIN' if getattr(db, 'backend', 'sqlite') == 'postgres' else 'BEGIN IMMEDIATE')
            # Serialize with deletion; late responses must not restore removed text.
            sql = 'SELECT removed_at FROM project_documents WHERE document_id=?'
            if getattr(db, 'backend', 'sqlite') == 'postgres': sql += ' FOR UPDATE'
            current = db.execute(sql, (self.row['document_id'],)).fetchone()
            payload = json.dumps(result, ensure_ascii=False) if result is not None and current and current['removed_at'] is None else None
            db.execute("""UPDATE document_ocr_units SET status=?,result_json=?,error_code=?
                WHERE document_id=? AND unit_key=? AND status='reserved'""",
                ('completed' if result is not None else 'failed', payload, error,
                 self.row['document_id'], key))
            db.commit()

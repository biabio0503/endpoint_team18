"""Collect activity listings on demand and publish each source independently."""
import argparse
from datetime import date
import json
from pathlib import Path
import signal
import sys


def run_source(source, mode, status=False, day=None):
    from config import DATABASE_URL, DB_BACKEND
    from psycopg.conninfo import conninfo_to_dict
    from repositories.postgres import connect_postgres
    db = None
    try:
        if DB_BACKEND != 'postgres' or not DATABASE_URL or conninfo_to_dict(DATABASE_URL).get('port') == '6543':
            raise ValueError('PostgreSQL direct/session connection required')
        if source == 'contestkorea':
            from crawling.contestkorea.store import Store
            from crawling.contestkorea.collector import collect
        else:
            from crawling.dacon.store import Store
            from crawling.dacon.crawler import collect
        db = connect_postgres(DATABASE_URL)
        store = Store(db.connection)
        discover = (lambda: collect(known=store.known_details())) if source == 'contestkorea' else collect
        result = store.status(day) if status else store.run(discover, mode)
        return {'source': source, **result}
    except Exception as error:
        return {'source': source, 'status': 'failed', 'error_code': type(error).__name__}
    finally:
        if db:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=('all', 'contestkorea', 'dacon'), default='all')
    parser.add_argument('--mode', choices=('scheduled', 'manual'), default='manual')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--date', type=date.fromisoformat)
    args = parser.parse_args()
    if args.date and not args.status:
        parser.error('--date requires --status')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/api/app'))
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    sources = ('contestkorea', 'dacon') if args.source == 'all' else (args.source,)
    failed = False
    for source in sources:
        result = run_source(source, args.mode, args.status, args.date)
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        failed |= result.get('status') in ('failed', 'partial')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())

"""Run once on the server: python -m crawling.dacon.run --mode manual."""
import argparse
from datetime import date
import json
from pathlib import Path
import signal
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('scheduled', 'manual'), default='manual')
    parser.add_argument('--status', action='store_true', help='Read last success and recent attempts; no crawling')
    parser.add_argument('--date', type=date.fromisoformat, help='KST history date (with --status)')
    args = parser.parse_args()
    if args.date and not args.status:
        parser.error('--date requires --status')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/api/app'))
    from config import DATABASE_URL, DB_BACKEND
    from repositories.postgres import connect_postgres
    from psycopg.conninfo import conninfo_to_dict
    from crawling.dacon.store import Store
    db = None
    try:
        if DB_BACKEND != 'postgres' or not DATABASE_URL:
            raise ValueError('PostgreSQL configuration required')
        if conninfo_to_dict(DATABASE_URL).get('port') == '6543':
            raise ValueError('Use a direct connection or session pooler on port 5432')
        db = connect_postgres(DATABASE_URL)
        store = Store(db.connection)
        if args.status:
            result = store.status(args.date)
        else:
            from crawling.dacon.crawler import collect
            def stop(signum, frame):
                raise SystemExit(128 + signum)
            signal.signal(signal.SIGTERM, stop)
            result = store.run(collect, args.mode)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 1 if result.get('status') in ('failed', 'partial') else 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_code': type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        if db:
            db.close()


if __name__ == '__main__':
    sys.exit(main())

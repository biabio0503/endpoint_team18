"""Internal fixture commands and an explicit, safe live Contest Korea probe."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from repositories.plans import migrate
from config import DB_BACKEND
from services.external_collection import init_fixtures,enqueue,process_once,retry,status,inspect,collect_contestkorea

def main():
    parser=argparse.ArgumentParser(description='fixture 수집 및 Contest Korea 실데이터 확인')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init-fixtures')
    sub.add_parser('contestkorea', help='서버 환경변수 키로 공모전·대외활동 실제 조회 (DB 불필요)')
    p=sub.add_parser('enqueue');p.add_argument('source_id');p.add_argument('--fixture-set',default='v1');p.add_argument('--job-key')
    p=sub.add_parser('work');p.add_argument('--drain',action='store_true')
    p=sub.add_parser('status');p.add_argument('job_id')
    p=sub.add_parser('retry');p.add_argument('job_id')
    p=sub.add_parser('inspect');p.add_argument('source_id')
    args=parser.parse_args()
    if args.command == 'contestkorea':
        result = collect_contestkorea()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if any(s['status'] != 'success' for s in result['sources']) else 0
    if DB_BACKEND != 'sqlite':
        print('외부 수집은 PostgreSQL에 아직 연결되지 않았습니다.', file=sys.stderr);return 2
    migrate()
    try:
        if args.command=='init-fixtures':init_fixtures();result={'registered':'fixture only','network_access':False}
        elif args.command=='enqueue':
            job_id,created=enqueue(args.source_id,args.fixture_set,args.job_key);result={'job_id':job_id,'created':created}
        elif args.command=='work':
            result=[]
            while True:
                job=process_once()
                if job is None:break
                result.append(job)
                if not args.drain:break
        elif args.command=='status':
            result=status(args.job_id)
            if result is None:raise ValueError('unknown_job')
        elif args.command=='retry':
            if not retry(args.job_id):raise ValueError('job_not_retryable')
            result={'job_id':args.job_id,'status':'queued'}
        else:result=inspect(args.source_id)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if args.command=='work' and any(job.get('status')=='failed' for job in result) else 0
    except ValueError as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())

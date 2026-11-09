"""Opt-in real Gemini + Himalayas smoke test; does not connect to or write a database."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # Load existing optional apps/api/.env without printing credentials.
from services.job_skill_analysis import analyze_job_skills

CASES = {
    'data': ('데이터 분석 분야에 관심이 있어요', '데이터 분석가'),
    'backend': ('웹 서버와 데이터베이스 개발에 관심이 있어요', '백엔드 개발자'),
    'ml': ('인공지능 모델의 학습과 서비스 적용에 관심이 있어요', '머신러닝 엔지니어'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['all', *CASES], default='all')
    parser.add_argument('--limit', type=int, choices=range(1, 21), default=20)
    parser.add_argument('--output', type=Path, help='Optional complete JSON report (contains public job evidence)')
    parser.add_argument('--pause-between-cases', type=float, default=65,
                        help='Pause between examples to allow request quota to refill (default: 65 seconds)')
    args = parser.parse_args()
    if not os.environ.get('GEMINI_API_KEY', '').strip():
        print('GEMINI_API_KEY가 설정되지 않았습니다. apps/api/.env 또는 서버 환경변수를 확인하세요.', file=sys.stderr)
        return 2
    results = {}
    for name, (goal, role) in CASES.items():
        if args.case not in ('all', name):
            continue
        if results and args.pause_between_cases > 0:
            print(json.dumps({'phase': 'quota_pause', 'seconds': args.pause_between_cases}), flush=True)
            time.sleep(args.pause_between_cases)
        print(json.dumps({'case': name, 'phase': 'starting', 'limit': args.limit}, ensure_ascii=False), flush=True)
        result = analyze_job_skills(goal, role, args.limit)
        results[name] = result
        print(json.dumps({'case': name, 'status': result['status'], 'canonical_role': result['canonical_role'],
                          'keyword_details': result['keyword_details'], 'collection_summary': result['collection_summary'],
                          'selection_summary': result['selection_summary'], 'analysis_summary': result['analysis_summary'],
                          'representative_skills': [{'name': s['name'], 'mentioned_job_count': s['mentioned_job_count'],
                                                     'evidence': s['evidence'][:1]} for s in result['skills'][:5]],
                          'errors': result['errors']}, ensure_ascii=False), flush=True)
        if args.output:
            args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    return int(any(r['status'] not in ('success', 'partial') or not r['analysis_summary']['analyzed_jobs'] for r in results.values()))


if __name__ == '__main__':
    raise SystemExit(main())

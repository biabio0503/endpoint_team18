"""Explicit small real Gemini/Himalayas E2E, using a disposable SQLite DB and synthetic text."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv
    load_dotenv(root / '.env', override=False)
    if not os.environ.get('GEMINI_API_KEY', '').strip():
        print('GEMINI_API_KEY가 설정되지 않았습니다.', file=sys.stderr)
        return 2
    report = {'fixture': 'synthetic first-person project document', 'job_limit': args.limit,
              'model': os.environ.get('GEMINI_MODEL', '').strip() or 'gemini-3.5-flash'}
    with tempfile.TemporaryDirectory(prefix='team18-project-live-') as tmp:
        # Never connect to the deployment DB or its storage, even if .env enables them.
        os.environ.update(ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'live.db'),
                          ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
                          ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000', RENDER='false')
        from fastapi.testclient import TestClient
        from app.main import app
        from worker.documents import run_once
        from services.gemini_jobs import _generate
        from services.job_skill_analysis import analyze_job_skills
        with patch('app.main.start_worker', return_value=None), TestClient(app, headers={'Origin': 'http://localhost:3000'}) as client, \
             patch('services.gemini_jobs._generate', wraps=_generate) as jobs_ai, \
             patch('services.gemini_projects._generate', wraps=_generate) as projects_ai:
            def checked(response):
                if response.status_code >= 400:
                    raise RuntimeError(f'API failed: {response.status_code}, {response.json().get("error")}')
                return response.json()
            rid = checked(client.post('/api/roadmap-inputs'))['request_id']
            base = '/api/roadmap-inputs/' + rid
            plan = checked(client.patch(base, json={'expected_input_revision': 0,
                'changes': {'career_goal': '데이터 분석 분야에서 데이터 기반 문제를 해결하고 싶습니다.', 'target_role': '데이터 분석가'}}))
            text = '개인 데이터 분석 프로젝트\n제가 Python을 사용하여 결측값을 처리하고 데이터 전처리 코드를 직접 작성했습니다.\n제가 Matplotlib을 사용하여 월별 추이 차트를 직접 작성했습니다.\n팀은 Docker로 실행 환경을 구성했습니다.'
            upload = checked(client.post(base + '/documents', data={'expected_input_revision': str(plan['input_revision'])},
                                        files={'file': ('synthetic-project.txt', text.encode(), 'text/plain')}))
            assert run_once()
            doc = upload['document']['document_id']
            source = checked(client.get(f'{base}/documents/{doc}/extractions/1'))
            report['text_extracted_exactly'] = source['extracted_text'] == text
            revision = checked(client.get(base))['input_revision']
            print(json.dumps({'phase': 'project_analysis', 'limit': args.limit}), flush=True)
            analysis = checked(client.post(base + '/project-experience-analysis', json={'expected_input_revision': revision}))
            report['project_status'] = analysis['status']
            report['project_errors'] = analysis['errors']
            report['verified_experiences'] = analysis['verified_experiences']
            report['all_quotes_match'] = all(text[e['evidence_start']:e['evidence_end']] == e['evidence_text'] for e in analysis['experiences'])
            python = next((e for e in analysis['experiences'] if e['skill_name'] == 'Python'), None)
            if python:
                analysis = checked(client.patch(f'{base}/project-experiences/{python["experience_id"]}/confirmation',
                    json={'expected_input_revision': revision, 'status': 'confirmed'}))
                report['answer_persisted'] = any(e['user_confirmation'] == 'confirmed' for e in analysis['experiences'])
                report['project_user_answers'] = {e['skill_name']: e['user_confirmation'] for e in analysis['experiences']}
            # A quota failure ends the live run; it must not spend more job requests.
            if any(e['code'] == 'gemini_rate_limited' for e in analysis['errors']):
                report['status'] = 'rate_limited'
            else:
                print(json.dumps({'phase': 'job_analysis', 'limit': args.limit}), flush=True)
                with patch('api.routes.job_skill_analysis.analyze_job_skills', side_effect=lambda goal, role: analyze_job_skills(goal, role, args.limit)):
                    jobs = checked(client.post(base + '/job-skill-analysis', json={}))
                comparison = checked(client.get(base + '/skill-comparison'))
                report['job_status'] = jobs['status']
                report['job_errors'] = jobs['errors']
                report['analyzed_jobs'] = jobs['analysis_summary']['analyzed_jobs']
                report['comparison_status'] = comparison['status']
                report['skills'] = {c['skill_name']: {'student_status': c['student_status'], 'project_evidence_count': len(c['project_evidence']),
                                    'job_evidence_count': len(c['job_evidence'])} for c in comparison['comparisons']}
                before = (jobs_ai.call_count, projects_ai.call_count)
                if jobs['status'] in ('success', 'partial'):
                    checked(client.post(base + '/job-skill-analysis', json={}))
                checked(client.post(base + '/project-experience-analysis', json={'expected_input_revision': analysis['input_revision']}))
                checked(client.get(base + '/skill-comparison'))
                report['revisit_without_gemini'] = before == (jobs_ai.call_count, projects_ai.call_count)
                report['status'] = 'success' if (python and report.get('answer_persisted') and report['revisit_without_gemini']
                    and report['skills'].get('Python', {}).get('student_status') == 'confirmed_experience'
                    and report['skills'].get('SQL', {}).get('student_status') == 'not_verified') else 'incomplete'
            report['gemini_operations'] = {'project': projects_ai.call_count, 'job': jobs_ai.call_count}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.write_text(output + '\n')
    return 0 if report.get('status') == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())

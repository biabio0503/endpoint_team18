"""Real Gemini generation from existing verified job output and exported curriculum references.

All writes go to a fresh temporary SQLite DB. Never opens a deployment DB, reruns
job/project extraction, or invents courses/skills. SQL answers are synthetic test-user input.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-snapshot', type=Path, required=True)
    parser.add_argument('--snapshot-key', default='data')
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', action='store_true', help='One additional call after course completion and SQL answer deferred.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv
    load_dotenv(root / '.env', override=False)
    jobs = json.loads(args.job_snapshot.read_text())
    if args.snapshot_key: jobs = jobs[args.snapshot_key]
    catalog = json.loads(args.catalog.read_text())
    if jobs['status'] not in ('success', 'partial') or not any(s['name'] == 'SQL' for s in jobs['skills']):
        raise SystemExit('Existing verified SQL evidence is required; no replacement is fabricated.')
    report = {'provider': 'real Gemini', 'source_job_snapshot': str(args.job_snapshot), 'reference_catalog': catalog['catalog']['catalog_id'],
              'fixture': 'synthetic user answers, existing verified overseas jobs and real curriculum; no project document',
              'model': os.environ.get('GEMINI_MODEL', '').strip() or 'gemini-3.5-flash', 'status': 'incomplete'}
    with tempfile.TemporaryDirectory(prefix='team18-roadmap-live-') as tmp:
        os.environ.update(ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'live.db'),
            ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0', ROADMAP_INSECURE_LOCAL_COOKIE='1',
            ROADMAP_APP_ORIGIN='http://localhost:3000', RENDER='false')
        from fastapi.testclient import TestClient
        from app.main import app
        from repositories.plans import connect, migrate
        from repositories.experience_analysis import AnalysisRepository
        from services.project_experience import job_basis
        from services.gemini_roadmap import generate_roadmap
        def audited_generation(data):
            generated = generate_roadmap(data)
            # This explicit test report is local; keep rejected suggestions for manual diagnosis.
            report.setdefault('model_responses', []).append(generated.model_dump())
            return generated
        migrate()
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            # Copy only known reference columns; never import users, selections or database SQL.
            for table, records in [('universities', [catalog['university']]), ('departments', [catalog['department']]),
                                   ('course_catalogs', [catalog['catalog']])]:
                allowed = {r['name'] for r in db.execute('PRAGMA table_info(' + table + ')')}
                for record in records:
                    fields = [k for k in record if k in allowed]
                    db.execute(f'INSERT INTO {table}({",".join(fields)}) VALUES({",".join("?" for _ in fields)})', [record[k] for k in fields])
            allowed = {r['name'] for r in db.execute('PRAGMA table_info(catalog_courses)')}
            for c in catalog['courses']:
                db.execute('INSERT INTO courses(course_id,university_id,canonical_name) VALUES(?,?,?)', (c['course_id'], c['university_id'], c['canonical_name']))
                fields = [k for k in c if k in allowed]
                db.execute(f'INSERT INTO catalog_courses({",".join(fields)}) VALUES({",".join("?" for _ in fields)})', [c[k] for k in fields])
            db.commit()
        with patch('app.main.start_worker', return_value=None), TestClient(app, headers={'Origin': 'http://localhost:3000'}) as client, \
             patch('api.routes.roadmaps.generate_roadmap', wraps=audited_generation) as ai, \
             patch('api.routes.job_skill_analysis.analyze_job_skills', side_effect=AssertionError('No job reanalysis')), \
             patch('services.project_experience.extract_project_experiences', side_effect=AssertionError('No project reanalysis')):
            def checked(response):
                if response.status_code >= 400:
                    report['error'] = response.json(); return None
                return response.json()
            plan = checked(client.post('/api/roadmap-inputs'))
            base = '/api/roadmap-inputs/' + plan['request_id']
            checked(client.patch(base, json={'expected_input_revision': 0, 'changes': {
                'career_goal': jobs['career_goal'], 'target_role': jobs['target_role'],
                'university_id': catalog['university']['university_id'], 'department_id': catalog['department']['department_id'],
                'catalog_id': catalog['catalog']['catalog_id'], 'year_level': 3}}))
            with closing(connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM roadmap_inputs WHERE request_id=?', (plan['request_id'],)).fetchone()
                snapshot = AnalysisRepository(db).save_job(plan['request_id'], job_basis(row), row['input_revision'], jobs)
                db.commit()
            def current(): return checked(client.get(base))
            def answer(status):
                return checked(client.post(base + '/skill-comparison/answers', json={'expected_input_revision': current()['input_revision'],
                    'snapshot_id': snapshot['snapshot_id'], 'skill_name': 'SQL', 'status': status}))
            def review():
                p = current()
                return checked(client.post(base + '/course-selection-review', json={'catalog_id': catalog['catalog']['catalog_id'],
                    'expected_input_revision': p['input_revision'], 'expected_selection_revision': p['selection_revision'], 'reported_missing_courses': False}))
            answer('no_experience'); review()
            print(json.dumps({'phase': 'real_roadmap_generation', 'reference_courses': len(catalog['courses'])}), flush=True)
            result = checked(client.post(base + '/roadmap', json={'expected_input_revision': current()['input_revision']}))
            if result:
                report['scenario_a'] = result
                run, task = result['run_id'], result['roadmap'][0]['tasks'][0]['task_id']
                before = current()['input_revision']
                checked(client.patch(f'{base}/roadmaps/{run}/tasks/{task}', json={'is_completed': True, 'expected_progress_version': 0}))
                restored = checked(client.get(base + '/roadmap'))
                reused = checked(client.post(base + '/roadmap', json={'expected_input_revision': before}))
                report['reused_without_ai'] = ai.call_count == 1 and reused['run_id'] == run
                report['progress_restored'] = restored['progress']['completed'] == 1 and current()['input_revision'] == before
                report['sql_no_experience_preserved'] = 'SQL' in result['preparation_summary']['learning_candidates']
                if args.compare and result['recommended_courses']:
                    # Change only real selected course IDs; no invented project confirmation.
                    ids = [c['course_id'] for c in result['recommended_courses']]
                    p = current()
                    checked(client.patch(base + '/course-selections', json={'catalog_id': catalog['catalog']['catalog_id'],
                        'expected_selection_revision': p['selection_revision'], 'changes': [{'course_id': cid, 'is_completed': True} for cid in ids]}))
                    answer('unknown'); review()
                    print(json.dumps({'phase': 'real_roadmap_comparison'}), flush=True)
                    second = checked(client.post(base + '/roadmap', json={'expected_input_revision': current()['input_revision']}))
                    report['scenario_c'] = second
                    if second:
                        report['completed_courses_excluded'] = not set(ids).intersection(c['course_id'] for c in second['recommended_courses'])
                        report['unverified_not_a_gap'] = 'SQL' in second['preparation_summary']['skills_to_verify'] and 'SQL' not in second['preparation_summary']['learning_candidates']
                        report['personalized_actions_changed'] = result['roadmap'] != second['roadmap']
                checks = ['reused_without_ai', 'progress_restored', 'sql_no_experience_preserved']
                if args.compare: checks += ['completed_courses_excluded', 'unverified_not_a_gap', 'personalized_actions_changed']
                report['status'] = 'success' if all(report.get(k) for k in checks) else 'incomplete'
            report['gemini_calls'] = ai.call_count
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('scenario_a', 'scenario_c', 'model_responses')}, ensure_ascii=False))
    return 0 if report['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())

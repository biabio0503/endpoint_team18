"""Real catalog IDs in disposable SQLite; no live providers or student data."""
from contextlib import closing
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from roadmap_scenario import RoadmapAPI, fake_roadmap
from api.domain import now
from course_groups import GROUPS_BY_CATALOG
from repositories.courses import CourseRepository
from repositories.plans import connect
from services.course_recommendations import available_courses, recommend

CATALOG = 'seoultech-cse-2026-major-v1'
GROUPS = GROUPS_BY_CATALOG[CATALOG]
ROWS = json.loads((Path(__file__).parents[1] / 'fixtures' / 'seoultech_cse_2026_catalog.json').read_text())['courses']
BY_NAME = {row['course_name']: row['course_id'] for row in ROWS}
ENGLISH, KOREAN = BY_NAME['Database'], BY_NAME['데이터베이스']
DATA_EN, DATA_KO = BY_NAME['Data Structure'], BY_NAME['자료구조']
ADVANCED = BY_NAME['고급소프트웨어공학']


def seed_catalog():
    with closing(connect()) as db:
        db.execute('INSERT INTO universities VALUES(?,?,TRUE) ON CONFLICT DO NOTHING',
                   ('seoultech', '서울과학기술대학교 (격리 테스트)'))
        db.execute('INSERT INTO departments VALUES(?,?,?,TRUE) ON CONFLICT DO NOTHING',
                   ('seoultech-cse', 'seoultech', '컴퓨터공학과'))
        db.execute('''INSERT INTO course_catalogs(catalog_id,department_id,version_label,
            scope_description,completeness_status,source_name,retrieved_at,is_selectable)
            VALUES(?,?,?,?,?,?,?,TRUE) ON CONFLICT DO NOTHING''',
            (CATALOG, 'seoultech-cse', '2026', 'Regression fixture', 'complete',
             'Read-only catalog snapshot', '2026-11-12T00:00:00+00:00'))
        for row in ROWS:
            db.execute('''INSERT INTO courses(course_id,university_id,canonical_name)
                VALUES(?,?,?) ON CONFLICT DO NOTHING''', (row['course_id'], 'seoultech', row['course_name']))
            db.execute('''INSERT INTO catalog_courses(catalog_id,course_id,course_name,
                course_code,credits,category,recommended_year,recommended_term)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                (CATALOG, *(row[k] for k in ('course_id', 'course_name', 'course_code', 'credits',
                                           'category', 'recommended_year', 'recommended_term'))))
        db.commit()


class CourseEquivalenceAPI(RoadmapAPI):
    def setUp(self):
        super().setUp()
        seed_catalog()
        response = self.client.patch(self.base, json={'expected_input_revision': self.revision(),
            'changes': {'university_id': 'seoultech', 'department_id': 'seoultech-cse',
                        'catalog_id': CATALOG, 'earned_credits': 30}})
        self.assertEqual(response.status_code, 200, response.text)

    def listing(self, **params):
        response = self.client.get(self.base + '/courses', params={'catalog_id': CATALOG, 'page_size': 100, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def legacy_select(self, *ids):
        # Preserve actual pre-group storage, bypassing the new toggle normalization.
        with closing(connect()) as db:
            repo = CourseRepository(db)
            for cid in ids:
                repo.save_state(self.rid, cid, CATALOG, True, now())
            repo.changed(self.rid, now())
            db.commit()

    def toggle(self, cid, completed, revision=None):
        if revision is None:
            revision = self.client.get(self.base).json()['selection_revision']
        return self.client.patch(self.base + '/course-selections', json={'catalog_id': CATALOG,
            'expected_selection_revision': revision, 'changes': [{'course_id': cid, 'is_completed': completed}]})

    def candidates(self):
        with closing(connect()) as db:
            return CourseRepository(db).recommendation_courses(self.rid, CATALOG)

    def saved_state(self):
        with closing(connect()) as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM input_course_states WHERE request_id=? ORDER BY course_id', (self.rid,))]

    def basic(self, expected, returned):
        self.assertEqual(set(available_courses(self.candidates())), expected)
        response = self.client.post(self.base + '/course-recommendations', json={})
        self.assertEqual(response.status_code, 200, response.text)
        ids = [c['course_id'] for c in response.json()['courses']]
        self.assertEqual(len(ids), min(5, len(expected)))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(ids) <= expected)
        return response.json()

    def roadmap(self, expected, chosen=ADVANCED):
        def provider(data):
            self.assertTrue({c['course_id'] for c in data['eligible_courses']} <= expected)
            with patch('roadmap_scenario.DB_COURSE', chosen):
                return fake_roadmap(data)
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=provider) as ai:
            response = self.make()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(ai.call_count, 1)
        return response.json()

    def test_all_16_pairs_search_filters_and_52_items_across_pages(self):
        self.assertEqual(len(ROWS), 68)
        all_items = self.listing()
        self.assertEqual(all_items['total'], 52)
        for group in GROUPS:
            korean, english = group['members']
            name = f"{korean['course_name']} ({english['course_name']})"
            expected = next(c for c in all_items['courses'] if c['course_id'] == korean['course_id'])
            self.assertEqual(expected['course_name'], name)
            self.assertEqual(expected['member_course_ids'], [korean['course_id'], english['course_id']])
            for query in (korean['course_name'], english['course_name'], english['course_name'].lower(),
                          korean['course_code'], english['course_code']):
                with self.subTest(group=group['group_number'], query=query):
                    matches = [c for c in self.listing(q=query)['courses'] if c['course_id'] == korean['course_id']]
                    self.assertEqual(matches, [expected])
            filtered = self.listing(year=expected['recommended_year'], category=expected['category'])
            self.assertIn(expected, filtered['courses'])
        for query in ('데이터베이스', 'Database', 'database'):
            self.assertEqual(self.listing(q=query)['total'], 1)
        for size in (10, 20, 50):
            pages = [self.listing(page=p, page_size=size) for p in range(1, (52 + size - 1) // size + 1)]
            ids = [c['course_id'] for page in pages for c in page['courses']]
            self.assertEqual(len(ids), 52)
            self.assertEqual(len(set(ids)), 52)
            self.assertEqual(ids, [c['course_id'] for c in all_items['courses']])

    def check_completion(self, selected):
        self.legacy_select(selected)
        before, plan = self.saved_state(), self.client.get(self.base).json()
        listing = self.listing()
        self.assertEqual([c['course_name'] for c in listing['selected_courses']], ['데이터베이스 (Database)'])
        self.assertEqual(listing['selection_summary'], {'count': 1, 'known_credits': 3.0, 'unknown_credits_count': 0})
        expected = set(available_courses(self.candidates()))
        self.assertEqual(len(expected), 51)
        self.assertTrue({ENGLISH, KOREAN}.isdisjoint(expected))
        basic = self.basic(expected, [ENGLISH, KOREAN, ADVANCED])
        self.assertTrue({ENGLISH, KOREAN}.isdisjoint(c['course_id'] for c in basic['courses']))
        self.jobs()
        run = self.roadmap(expected)
        self.assertEqual([c['course_id'] for c in run['recommended_courses']], [c['course_id'] for c in basic['courses']])
        self.assertEqual(self.saved_state(), before)
        self.assertEqual(self.client.get(self.base).json(), plan)
        self.assertEqual(plan['input']['earned_credits'], 30)

    def test_english_completion_excludes_both(self):
        self.check_completion(ENGLISH)

    def test_korean_completion_excludes_both(self):
        self.check_completion(KOREAN)

    def test_old_data_structure_and_database_selection(self):
        self.legacy_select(DATA_EN, ENGLISH)
        before = self.saved_state()
        listing = self.listing(page_size=1)
        self.assertEqual({c['course_name'] for c in listing['selected_courses']},
                         {'자료구조 (Data Structure)', '데이터베이스 (Database)'})
        self.assertTrue(all(c['is_completed'] for c in listing['selected_courses']))
        self.assertEqual(listing['selection_summary'], {'count': 2, 'known_credits': 6.0, 'unknown_credits_count': 0})
        self.assertEqual(self.listing(completed_only='true')['total'], 2)
        excluded = {DATA_EN, DATA_KO, ENGLISH, KOREAN}
        expected = set(available_courses(self.candidates()))
        self.assertEqual(len(expected), 50)
        self.assertTrue(expected.isdisjoint(excluded))
        basic = self.basic(expected, [*excluded, ADVANCED])
        self.assertTrue(excluded.isdisjoint(c['course_id'] for c in basic['courses']))
        self.jobs()
        self.roadmap(expected)
        self.assertEqual(self.saved_state(), before)

    def test_all_pairs_double_selection_counts_once_and_single_toggle_clears(self):
        self.legacy_select(*(m['course_id'] for group in GROUPS for m in group['members']))
        self.assertEqual(self.listing()['selection_summary'], {'count': 16, 'known_credits': 48.0, 'unknown_credits_count': 0})
        for group in GROUPS:
            korean, english = group['members']
            revision = self.listing()['selection_revision']
            response = self.toggle(korean['course_id'], False, revision)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['selection_revision'], revision + 1)
            # A fresh GET after each toggle is the same state a browser reload reads.
            self.assertFalse(next(c for c in self.listing()['courses'] if c['course_id'] == korean['course_id'])['is_completed'])
            stored = {s['course_id']: s['is_completed'] for s in self.saved_state()}
            self.assertFalse(stored[korean['course_id']])
            self.assertFalse(stored[english['course_id']])
        self.assertEqual(self.listing()['selection_summary']['count'], 0)
        self.assertEqual(self.toggle(ENGLISH, True).status_code, 200)
        self.assertEqual([s['course_id'] for s in self.saved_state() if s['is_completed']], [KOREAN])
        revision = self.listing()['selection_revision']
        self.assertEqual(self.toggle(KOREAN, True).json()['selection_revision'], revision)
        self.assertEqual(self.toggle(KOREAN, False, revision - 1).status_code, 409)
        self.assertTrue(self.listing(q='database')['courses'][0]['is_completed'])

    def test_conflicting_alias_batch_is_atomic(self):
        revision = self.listing()['selection_revision']
        response = self.client.patch(self.base + '/course-selections', json={'catalog_id': CATALOG,
            'expected_selection_revision': revision, 'changes': [
                {'course_id': KOREAN, 'is_completed': True}, {'course_id': ENGLISH, 'is_completed': False}]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.saved_state(), [])
        self.assertEqual(self.listing()['selection_revision'], revision)

    def test_uncompleted_group_recommended_once_with_bilingual_name(self):
        expected = set(available_courses(self.candidates()))
        self.assertEqual(len(expected), 52)
        self.assertIn(KOREAN, expected)
        self.assertNotIn(ENGLISH, expected)
        basic = self.basic(expected, [KOREAN, ENGLISH, KOREAN])
        self.assertEqual(len(basic['courses']), 5)
        self.jobs()
        run = self.roadmap(expected, KOREAN)
        self.assertEqual([c['course_id'] for c in run['recommended_courses']], [c['course_id'] for c in basic['courses']])
        self.assertEqual(self.saved_state(), [])

    def test_legacy_completion_regenerates_without_reselection(self):
        with patch('course_groups.GROUPS_BY_CATALOG', {}):
            self.legacy_select(ENGLISH)
            before, plan = self.saved_state(), self.client.get(self.base).json()
            expected = set(available_courses(self.candidates()))
            old_basic = self.basic(expected, [KOREAN])
            self.assertIn(KOREAN, expected)
            self.jobs()
            old_run = self.roadmap(expected, KOREAN)
        self.assertTrue(self.client.get(self.base + '/roadmap').json()['is_stale'])
        expected = set(available_courses(self.candidates()))
        self.assertTrue({ENGLISH, KOREAN}.isdisjoint(expected))
        self.basic(expected, [ADVANCED])
        new_run = self.roadmap(expected)
        self.assertNotEqual(new_run['basis_hash'], old_run['basis_hash'])
        self.assertEqual(self.saved_state(), before)
        self.assertEqual(self.client.get(self.base).json(), plan)

    def check_legacy_result(self, both):
        with patch('course_groups.GROUPS_BY_CATALOG', {}):
            self.jobs()
            with patch('api.routes.roadmaps.generate_roadmap', side_effect=fake_roadmap):
                response = self.make()
            self.assertEqual(response.status_code, 201, response.text)
            old = response.json()
            # Emulate a saved pre-ranking run; new generation now owns its list.
            with closing(connect()) as db:
                saved = json.loads(db.execute('SELECT result_json FROM roadmap_runs WHERE run_id=?', (old['run_id'],)).fetchone()['result_json'])
                english = {'course_id': ENGLISH, 'course_name': 'Database', 'related_skills': ['SQL'], 'evidence_refs': []}
                saved['recommended_courses'] = [english]
                for step in saved['roadmap']:
                    step['related_course_ids'] = [ENGLISH]
                if both:
                    saved['recommended_courses'].append({**english, 'course_id': KOREAN, 'course_name': '데이터베이스'})
                    saved['roadmap'][1]['related_course_ids'] = [KOREAN]
                    saved['roadmap'][2]['related_course_ids'] = [ENGLISH, KOREAN]
                db.execute('UPDATE roadmap_runs SET result_json=? WHERE run_id=?', (json.dumps(saved, ensure_ascii=False), old['run_id']))
                db.commit()
        with closing(connect()) as db:
            original = dict(db.execute('SELECT result_json,basis_json FROM roadmap_runs WHERE run_id=?', (old['run_id'],)).fetchone())
        with patch('api.routes.roadmaps.generate_roadmap') as ai:
            for path in ('/roadmap', '/roadmaps/' + old['run_id']):
                result = self.client.get(self.base + path)
                self.assertEqual(result.status_code, 200, result.text)
                result = result.json()
                self.assertEqual(len(result['recommended_courses']), 1)
                course = result['recommended_courses'][0]
                self.assertEqual(course['course_name'], '데이터베이스 (Database)')
                self.assertEqual(course['member_course_ids'], [KOREAN, ENGLISH])
                self.assertTrue(all(s['related_course_ids'] == [KOREAN] for s in result['roadmap']))
            progress = self.client.patch(self.base + '/roadmaps/' + old['run_id'] + '/tasks/task-1',
                json={'is_completed': True, 'expected_progress_version': 0})
            self.assertEqual(progress.status_code, 200, progress.text)
            self.assertEqual(progress.json()['progress']['completed'], 1)
            ai.assert_not_called()
        with closing(connect()) as db:
            self.assertEqual(dict(db.execute('SELECT result_json,basis_json FROM roadmap_runs WHERE run_id=?',
                                            (old['run_id'],)).fetchone()), original)

    def test_legacy_english_roadmap_reads_without_ai(self):
        self.check_legacy_result(False)

    def test_legacy_duplicate_roadmap_and_both_step_ids_read_without_ai(self):
        self.check_legacy_result(True)

    def test_programming_one_and_software_do_not_exclude_distinct_courses(self):
        self.legacy_select(BY_NAME['Introduction to Programming 1'], BY_NAME['Software Engineering'])
        candidates = set(available_courses(self.candidates()))
        self.assertNotIn(BY_NAME['프로그래밍입문(1)'], candidates)
        self.assertNotIn(BY_NAME['소프트웨어공학'], candidates)
        self.assertIn(BY_NAME['프로그래밍입문(2)'], candidates)
        self.assertIn(ADVANCED, candidates)
        result = self.basic(candidates, [BY_NAME['프로그래밍입문(2)'], ADVANCED])
        self.assertEqual(len(result['courses']), 5)

    def test_final_basic_response_and_roadmap_recheck_completion(self):
        self.legacy_select(ENGLISH)
        unsafe = [{'course_id': cid, 'completion_state': 'unconfirmed'}
                  for cid in (ENGLISH, KOREAN, ADVANCED, ADVANCED)]
        with patch('api.routes.recommendations.guarded_call', return_value=unsafe):
            response = self.client.post(self.base + '/course-recommendations', json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['courses']), 5)
        self.assertTrue({ENGLISH, KOREAN}.isdisjoint(c['course_id'] for c in response.json()['courses']))
        self.jobs()
        def invalid_provider(data):
            raw = fake_roadmap(data).model_dump()
            skill = next(s for s in data['skills'] if s['skill_name'] == 'SQL')
            raw['recommended_courses'] = [{'course_id': KOREAN, 'related_skills': ['SQL'],
                'evidence_refs': [skill['comparison_ref']], 'course_evidence': '데이터베이스',
                'reason': '후보', 'personalization_reason': '후보', 'course_role': 'foundation',
                'recommendation_confidence': 'limited'}]
            return raw
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=invalid_provider):
            response = self.make()
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json()['detail_code'], 'course_completed')
        with closing(connect()) as db:
            run = db.execute('SELECT result_json FROM roadmap_runs WHERE request_id=?', (self.rid,)).fetchone()
            self.assertIsNone(run['result_json'])


if __name__ == '__main__':
    names = [name for name in CourseEquivalenceAPI.__dict__ if name.startswith('test_')]
    suite = unittest.TestSuite(CourseEquivalenceAPI(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

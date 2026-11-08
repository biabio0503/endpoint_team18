import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import config  # Load the optional backend .env for the opt-in live test.
from services.course_recommendations import recommend
from services.gemini import recommend_ids, GeminiError


def course(cid, name, completed=False, description=None):
    return dict(course_id=cid, course_name=name, description_text=description, category='전공', recommended_year=2, recommended_term='1', is_completed=completed)


class RecommendationTest(unittest.TestCase):
    def setUp(self):
        self.courses = [course('data', '데이터 분석', description='통계 분석'), course('ml', '머신러닝'), course('math', '선형대수')]

    def test_goals_descriptions_and_completion(self):
        def model(profile, courses):
            self.assertIn('description_text', courses[0])
            self.assertIsNone(courses[1]['description_text'])
            return ['data'] if profile['career_goal'] == '데이터 분석' else ['ml', 'math']
        self.assertEqual([c['course_id'] for c in recommend({'career_goal':'데이터 분석'}, self.courses, 'unconfirmed', model)], ['data'])
        self.assertEqual([c['course_id'] for c in recommend({'career_goal':'머신러닝'}, self.courses, 'confirmed', model)], ['ml', 'math'])
        self.courses[1]['is_completed'] = True
        result = recommend({'career_goal':'머신러닝'}, self.courses, 'confirmed', lambda p, c: ['ml', 'math'])
        self.assertEqual([c['course_id'] for c in result], ['math'])

    def test_validation_dedup_limit_and_empty(self):
        courses = self.courses + [course(str(i), str(i)) for i in range(6)]
        result = recommend({}, courses, 'unconfirmed', lambda p, c: ['missing', 'data', 'data', 'ml', 'math', '0', '1', '2'])
        self.assertEqual([c['course_id'] for c in result], ['data', 'ml', 'math', '0', '1'])
        self.assertEqual(result[0]['completion_state'], 'unconfirmed')
        self.assertEqual(recommend({}, [], 'unconfirmed', lambda *a: self.fail('model called')), [])
        self.assertEqual(recommend({}, self.courses, 'confirmed', lambda *a: []), [])

    def test_sdk_schema_and_errors(self):
        client = Mock()
        client.models.generate_content.return_value.text = '{"recommended_course_ids":["data"]}'
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key', 'GEMINI_MODEL':'model-test'}), patch('google.genai.Client', return_value=client):
            self.assertEqual(recommend_ids({'career_goal':'데이터'}, self.courses), ['data'])
            kwargs=client.models.generate_content.call_args.kwargs
            self.assertEqual(kwargs['model'], 'model-test')
            self.assertEqual(kwargs['config'].response_mime_type, 'application/json')
            self.assertIn('recommended_course_ids', kwargs['config'].response_json_schema['properties'])
            client.models.generate_content.return_value.text = '{"recommended_course_ids":[42]}'
            with self.assertRaises(GeminiError) as error: recommend_ids({}, [])
            self.assertEqual(error.exception.code, 'gemini_invalid_response')
        with patch.dict(os.environ, {'GEMINI_API_KEY':''}):
            with self.assertRaises(GeminiError) as error: recommend_ids({}, [])
            self.assertEqual(error.exception.code, 'gemini_not_configured')

    def test_rate_limit_retries(self):
        class RateLimit(Exception): code=429
        client=Mock(); client.models.generate_content.side_effect=RateLimit()
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch('google.genai.Client', return_value=client), patch('services.gemini.time.sleep') as sleep:
            with self.assertRaises(GeminiError) as error: recommend_ids({}, [])
            self.assertEqual(error.exception.code, 'gemini_rate_limited')
            self.assertEqual(client.models.generate_content.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.5, 1.0])

    @unittest.skipUnless(os.getenv('GEMINI_LIVE_TEST') == '1' and os.getenv('GEMINI_API_KEY'), '실제 API 키와 GEMINI_LIVE_TEST=1 필요')
    def test_live_connection(self):
        ids = recommend_ids({'career_goal':'데이터 분석'}, [course('data', '데이터 분석')])
        self.assertIsInstance(ids, list)
        self.assertTrue(all(isinstance(i, str) for i in ids))

if __name__ == '__main__': unittest.main()

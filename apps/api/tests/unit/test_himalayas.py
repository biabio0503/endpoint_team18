import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from services import himalayas as h


def job(guid='https://himalayas.app/companies/acme/jobs/data-analyst', title='Senior Data Analyst'):
    return {'guid': guid, 'title': title, 'companyName': 'Acme', 'companySlug': 'acme',
            'categories': ['Analytics'], 'parentCategories': ['Data'], 'seniority': ['Senior'],
            'employmentType': 'Full Time', 'description': '<p>SQL &amp; Python</p><ul><li>First</li><li>Second<br>line</li></ul><script>bad()</script>',
            'excerpt': 'Example', 'pubDate': 1740200000, 'expiryDate': None,
            'locationRestrictions': ['US'], 'timezoneRestrictions': [], 'applicationLink': 'https://himalayas.app/apply/123'}


class HimalayasTest(unittest.TestCase):
    def test_keyword_mapping_priority_and_fallback(self):
        cases = [
            ('데이터 분석 관심', '데이터 분석가', ['Data Analyst', 'BI Analyst', 'Data Scientist']),
            ('데이터 분석 관심', '백엔드 개발자', ['Backend Engineer', 'Backend Developer']),
            ('인공지능 모델 개발 관심', None, ['Machine Learning Engineer', 'AI Engineer']),
            ('웹사이트 서버와 데이터베이스 개발', None, ['Backend Engineer', 'Backend Developer']),
            ('데이터 분석', 'Data Scientist', ['Data Scientist', 'Data Analyst']),
            ('anything', 'UX Designer', ['UX Designer']),
            ('anything', 'AI Engineer', ['AI Engineer', 'Machine Learning Engineer']),
        ]
        for goal, role, expected in cases:
            with self.subTest(role=role, goal=goal):
                entries, reason = h.generate_search_keywords(goal, role)
                self.assertIsNone(reason)
                self.assertEqual([e['keyword'] for e in entries], expected)
        self.assertEqual(h.generate_search_keywords('데이터 분석', '모르는 직무')[1], 'unmapped_role')
        self.assertEqual(h.generate_search_keywords('알 수 없는 관심 분야')[1], 'unmapped_goal')
        self.assertEqual(h.generate_search_keywords('data', 'hello')[1], 'unmapped_role')
        self.assertEqual(h.generate_search_keywords('데이터 분석')[0][-1]['relation'], 'related')

    def test_normalization_description_and_dates(self):
        entries, _ = h.generate_search_keywords('데이터 분석')
        item = h.normalize_job(job(), 'Data Analyst', entries)
        self.assertEqual(item['description_html'], job()['description'])
        self.assertEqual(item['description_text'], 'SQL & Python\nFirst\nSecond\nline')
        self.assertEqual(item['published_at'], '2025-02-22T04:53:20Z')
        self.assertIsNone(item['expires_at'])
        self.assertEqual(item['source_url'], job()['guid'])
        self.assertEqual(item['application_link'], job()['applicationLink'])
        self.assertEqual(item['match_type'], 'direct')
        self.assertEqual(h.normalize_job(job(title='Data Scientist'), 'Data Scientist', entries)['match_type'], 'related')
        self.assertEqual(h.normalize_job(job(title='Sales Manager'), 'Data Analyst', entries)['match_type'], 'unverified')
        self.assertIsNone(h.normalize_job(job(guid='https://evil.example/job'), 'Data Analyst', entries)['source_url'])

    def test_dedup_partial_and_page_limits(self):
        def request(keyword, page):
            if keyword == 'BI Analyst':
                return {'jobs': [job(), job('https://himalayas.app/companies/acme/jobs/bi', 'BI Analyst')] if page == 1 else []}
            if keyword == 'Data Scientist':
                raise h.SearchError('http_500', 500)
            return {'jobs': [job()] if page == 1 else []}
        with patch.object(h, '_request_page', side_effect=request) as mock:
            result = h.fetch_jobs('데이터 분석', limit=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['total_collected'], 2)
        self.assertEqual(result['jobs'][0]['matched_keywords'], ['Data Analyst', 'BI Analyst'])
        self.assertEqual(result['searches'][1]['received_count'], 2)
        self.assertEqual(result['errors'][0]['code'], 'http_500')
        self.assertLessEqual(max(c.args[1] for c in mock.call_args_list), 2)

    def test_empty_invalid_input_and_page_two_failure(self):
        with patch.object(h, '_request_page', return_value={'jobs': []}) as request:
            result = h.fetch_jobs('unknown', 'Backend Engineer')
            self.assertEqual((result['status'], result['total_collected']), ('success', 0))
            self.assertEqual(request.call_count, 2)
        with patch.object(h, '_request_page') as request:
            self.assertEqual(h.fetch_jobs('모르는 목표')['errors'][0]['code'], 'unmapped_goal')
            request.assert_not_called()
        with patch.object(h, '_request_page', side_effect=[{'jobs': [job()]}, h.SearchError('timeout'), {'jobs': []}]):
            result = h.fetch_jobs('백엔드')
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['searches'][0]['status'], 'partial')
            self.assertEqual(result['total_collected'], 1)
        for value in (0, 101, True):
            with self.assertRaises(ValueError): h.fetch_jobs('x', limit=value)

    def test_request_parameters_headers_and_invalid_responses(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({'jobs': [job()]}).encode()))
        response.__exit__ = Mock(return_value=False)
        opener = Mock(); opener.open.return_value = response
        with patch.object(h, 'build_opener', return_value=opener), patch.dict(os.environ, {'HIMALAYAS_API_KEY': 'secret'}):
            self.assertEqual(len(h._request_page('Data Analyst', 1)['jobs']), 1)
        req = opener.open.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(req.full_url).query), {'q': ['Data Analyst'], 'page': ['1'], 'sort': ['relevant']})
        self.assertEqual(req.get_header('Authorization'), 'Bearer secret')
        for raw, code in [(b'broken', 'invalid_json'), (b'{"jobs":{}}', 'invalid_response'), (b'{"jobs":[{}]}', 'invalid_response')]:
            response.__enter__.return_value = io.BytesIO(raw)
            with patch.object(h, 'build_opener', return_value=opener), self.assertRaises(h.SearchError) as error:
                h._request_page('Data Analyst', 1)
            self.assertEqual(error.exception.code, code)

    def test_retry_after_and_timeout(self):
        opener = Mock()
        failure = HTTPError(h.SEARCH_URL, 429, 'error', {'Retry-After': '2'}, None)
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"jobs":[]}'))
        response.__exit__ = Mock(return_value=False)
        opener.open.side_effect = [failure, response]
        with patch.object(h, 'build_opener', return_value=opener), patch.object(h.time, 'sleep') as sleep, patch.dict(os.environ, {'HIMALAYAS_API_KEY': ''}):
            self.assertEqual(h._request_page('Backend Engineer', 1), {'jobs': []})
            sleep.assert_called_once_with(2)
            self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
        opener.open.side_effect = TimeoutError()
        with patch.object(h, 'build_opener', return_value=opener), patch.object(h.time, 'sleep'), self.assertRaises(h.SearchError) as error:
            h._request_page('Backend Engineer', 1)
        self.assertEqual(error.exception.code, 'timeout')

    def test_http_and_connection_errors_retry_policy(self):
        for status in (400, 401, 429, 500):
            opener = Mock()
            opener.open.side_effect = HTTPError(h.SEARCH_URL, status, 'error', {'Retry-After': '30'}, None)
            with patch.object(h, 'build_opener', return_value=opener), patch.object(h.time, 'sleep') as sleep, self.assertRaises(h.SearchError) as error:
                h._request_page('Data Analyst', 1)
            self.assertEqual(error.exception.code, f'http_{status}')
            self.assertEqual(opener.open.call_count, 2 if status == 500 else 1)
            if status == 429: sleep.assert_not_called()
        opener = Mock(); opener.open.side_effect = URLError('network')
        with patch.object(h, 'build_opener', return_value=opener), patch.object(h.time, 'sleep'), self.assertRaises(h.SearchError) as error:
            h._request_page('x', 1)
        self.assertEqual(error.exception.code, 'connection_error')
        with patch.object(h, '_request_page', side_effect=h.SearchError('http_429', 429, 30)) as request:
            result = h.fetch_jobs('데이터 분석')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['searches'][1]['status'], 'skipped')


if __name__ == '__main__': unittest.main()

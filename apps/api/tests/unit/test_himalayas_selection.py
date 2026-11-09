from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from services import himalayas as h

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
KEYWORDS, _ = h.generate_search_keywords('데이터 분석')


def raw(number, title='Data Analyst', seniority=None, description='<p>SQL</p>', expiry=None, company=None):
    return {'guid': f'https://himalayas.app/companies/company{number}/jobs/job{number}',
            'title': title, 'companyName': company or f'Company {number}', 'companySlug': company or f'company{number}',
            'seniority': seniority, 'description': description, 'expiryDate': expiry,
            'categories': ['Data Analyst'], 'parentCategories': ['Data'], 'applicationLink': 'https://example.com/apply'}


def candidate(number, title='Data Analyst', level=None, keyword='Data Analyst', **kwargs):
    return h.normalize_job(raw(number, title, level, **kwargs), keyword, KEYWORDS)


class SelectionTest(unittest.TestCase):
    def test_title_before_categories_and_role_boundaries(self):
        cases = [('Junior Data Analyst', 'direct'), ('Senior Data Analyst', 'direct'),
                 ('Data Scientist', 'related'), ('Predictive CRM AI Analyst', 'unverified'),
                 ('Data Analystics Engineer', 'unverified'), ('Sales Manager', 'unverified')]
        for title, expected in cases:
            with self.subTest(title=title):
                item = candidate(1, title)
                self.assertEqual(item['match_type'], expected)
                self.assertEqual(item['match_reason'], 'no_title_role_match' if expected == 'unverified' else 'title_and_category_role_match' if expected == 'direct' else 'title_role_match')

    def test_seniority_conflicts_and_original(self):
        cases = [(['Entry-level'], 'Data Analyst', 'entry'), (['Mid-level'], 'Data Analyst', 'mid'),
                 (['Senior'], 'Data Analyst', 'senior'), (['Director'], 'Data Analyst', 'senior'),
                 ([], 'Junior Data Analyst', 'entry'), (None, 'Staff Data Analyst', 'senior'),
                 (['Mid-level', 'Senior'], 'Data Analyst', 'unknown'),
                 (['Senior'], 'Junior Data Analyst', 'unknown'), (['Unrecognized'], 'Senior Data Analyst', 'unknown'),
                 ([], 'Data Analyst', 'unknown')]
        for value, title, expected in cases:
            with self.subTest(value=value, title=title):
                self.assertEqual(h.seniority_group(value, title), expected)
                self.assertEqual(candidate(1, title, value)['seniority'], value)

    def test_selection_relevance_round_robin_and_dedup(self):
        first = [raw(i, 'Data Analyst', ['Entry-level']) for i in range(1, 7)]
        second = [raw(i, 'BI Analyst', ['Entry-level']) for i in range(10, 16)] + [first[0]]
        related = [raw(i, 'Data Scientist', ['Entry-level']) for i in range(20, 26)]
        def request(keyword, page):
            return {'jobs': {'Data Analyst': first, 'BI Analyst': second, 'Data Scientist': related}[keyword] if page == 1 else []}
        with patch.object(h, '_request_page', side_effect=request):
            result = h.fetch_jobs('데이터 분석', limit=5)
        self.assertEqual(result['total_collected'], 5)
        self.assertEqual(result['selection_summary']['direct_count'], 4)
        self.assertEqual(result['selection_summary']['related_count'], 1)
        self.assertEqual([j['title'] for j in result['jobs']].count('BI Analyst'), 2)
        self.assertEqual(result['jobs'][0]['matched_keywords'], ['Data Analyst', 'BI Analyst'])
        self.assertEqual(len({j['id'] for j in result['jobs']}), 5)
        self.assertEqual(result['selection_summary']['duplicate_occurrences'], 1)
        self.assertEqual(result['searches'][1]['received_count'], 7)

    def test_exclusions_overlap_and_source_status(self):
        past = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
        candidates = [candidate(1, 'Sales Manager', description=' '), candidate(2, expiry=past),
                      candidate(3, description=' <p> </p> '), candidate(4), candidate(5)]
        candidates[-1]['source_url'] = None
        selected, summary = h.select_jobs(candidates, KEYWORDS, 10, NOW)
        self.assertEqual(len(selected), 2)
        self.assertEqual(summary['excluded_count'], 3)
        self.assertEqual(summary['excluded_by_reason'], {'unverified': 1, 'missing_description': 2, 'expired': 1})
        self.assertFalse(selected[-1]['source_verified'])
        self.assertEqual(selected[-1]['analysis_reasons'], ['eligible'])
        self.assertTrue(all(j['analysis_eligible'] for j in selected))
        self.assertEqual(summary['source_unverified_candidates'], 1)
        self.assertEqual(selected[-1]['application_link'], 'https://example.com/apply')

    def test_related_only_small_pool_and_direct_priority(self):
        jobs = [candidate(1, 'Data Scientist'), candidate(2, 'Data Scientist'), candidate(3, 'Sales Manager')]
        selected, summary = h.select_jobs(jobs, KEYWORDS, 8, NOW)
        self.assertEqual((len(selected), summary['related_count']), (2, 2))
        jobs += [candidate(4, 'Senior Data Analyst', ['Senior'])]
        selected, _ = h.select_jobs(jobs, KEYWORDS, 2, NOW)
        self.assertEqual([j['match_type'] for j in selected], ['direct', 'related'])

    def test_seniority_soft_cap_and_determinism(self):
        jobs = ([candidate(i, 'Senior Data Analyst', ['Senior']) for i in range(1, 9)] +
                [candidate(10, 'Junior Data Analyst', ['Entry-level']), candidate(11, 'Data Analyst', ['Mid-level']),
                 candidate(12, 'Data Analyst')])
        first, summary = h.select_jobs(jobs, KEYWORDS, 4, NOW)
        second, _ = h.select_jobs(jobs, KEYWORDS, 4, NOW)
        self.assertEqual([j['id'] for j in first], [j['id'] for j in second])
        self.assertEqual(summary['seniority_distribution'], {'entry': 1, 'mid': 1, 'senior': 1, 'unknown': 1})
        first, summary = h.select_jobs(jobs[:8], KEYWORDS, 4, NOW)
        self.assertEqual(summary['seniority_distribution']['senior'], 4)

    def test_company_diversity_as_tie_breaker(self):
        jobs = [candidate(1, level=['Entry-level'], company='same'), candidate(2, level=['Entry-level'], company='same'),
                candidate(3, level=['Entry-level'], company='other')]
        selected, _ = h.select_jobs(jobs, KEYWORDS, 2, NOW)
        self.assertEqual([j['company'] for j in selected], ['same', 'other'])

    def test_second_page_when_related_candidates_dominate(self):
        def request(keyword, page):
            if keyword == 'Data Analyst':
                return {'jobs': [raw(1)] if page == 1 else [raw(2), raw(3), raw(4)]}
            if keyword == 'Data Scientist' and page == 1:
                return {'jobs': [raw(i, 'Data Scientist') for i in range(10, 15)]}
            return {'jobs': []}
        with patch.object(h, '_request_page', side_effect=request) as mock:
            result = h.fetch_jobs('데이터 분석', limit=5)
        self.assertIn(('Data Analyst', 2), [call.args for call in mock.call_args_list])
        self.assertEqual(result['selection_summary']['direct_count'], 4)
        self.assertEqual(result['selection_summary']['related_count'], 1)

    def test_partial_failures_and_second_page(self):
        def request(keyword, page):
            if keyword == 'BI Analyst':
                raise h.SearchError('http_500', 500)
            if keyword == 'Data Analyst':
                return {'jobs': [raw(1)] if page == 1 else [raw(2)]}
            return {'jobs': []}
        with patch.object(h, '_request_page', side_effect=request):
            result = h.fetch_jobs('데이터 분석', limit=3)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['total_collected'], 2)
        self.assertEqual(result['errors'][0]['code'], 'http_500')
        self.assertEqual(result['searches'][0]['pages_succeeded'], 2)
        self.assertEqual(result['selection_summary']['total_candidates'], 2)


if __name__ == '__main__': unittest.main()

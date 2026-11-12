from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))

from experience_activity_regressions import BIKE_DATA, FRONTEND, postings

from fastapi.testclient import TestClient
import main

headers = {'Origin': 'http://localhost:3000'}
sources = {'kind': 'competition', 'source': 'contestkorea', 'status': 'success'}
item = {'id': 'real-contract-fixture', 'kind': 'competition', 'title': '데이터 분석 경진대회', 'category': '데이터',
        'target': '대학생', 'period': '상시 접수', 'host': '테스트', 'url': 'https://www.contestkorea.com/sub/view.php?str_no=test'}

with TestClient(main.app, headers=headers) as client, patch('api.routes.activities.load_contestkorea_catalog', return_value=([item], sources)) as fetch, \
        patch('services.gemini_projects.extract_project_experiences', side_effect=AssertionError('No Gemini')):
    plan = client.post('/api/roadmap-inputs').json()
    rid = plan['request_id']
    base = f'/api/roadmap-inputs/{rid}'
    path = base + '/activities'
    assert client.get(path).status_code == 422
    assert fetch.call_count == 0
    changed = client.patch(base, json={'expected_input_revision': 0, 'changes': {'career_goal': '데이터 분석가'}})
    assert changed.status_code == 200, changed.text
    response = client.get(path)
    assert response.status_code == 200, response.text
    data = response.json()
    assert response.headers['cache-control'] == 'no-store'
    assert data['status'] == 'partial' and len(data['activities']) == 1
    assert data['target_role'] is None and data['input_revision'] == 1
    assert data['activities'][0]['reasons'] and data['activities'][0]['deadline_label'] == '상시 접수'
    # No document, job analysis or generated roadmap was needed.
    assert client.get(base).json()['request_id'] == rid
    fetch.return_value = ([], {'kind': 'competition', 'status': 'error'})
    assert client.get(path).json()['status'] == 'error'
    assert client.get(base).status_code == 200
    assert client.get(base + '/roadmap').status_code == 200
    count = fetch.call_count
    with TestClient(main.app, headers=headers) as other:
        assert other.get(path).status_code == 401
        other.post('/api/roadmap-inputs')
        assert other.get(path).status_code == 404
    assert fetch.call_count == count
    def changed_goal(*args):
        client.patch(base, json={'expected_input_revision': 1, 'changes': {'career_goal': '마케팅'}})
        return [item], sources
    fetch.side_effect = changed_goal
    assert client.get(path).status_code == 409
    fetch.side_effect = None
    fetch.return_value = (postings(), sources)
    for profile, expected_ids in ((FRONTEND, set()), (BIKE_DATA, {'2', '3'})):
        revision = client.get(base).json()['input_revision']
        response = client.patch(base, json={'expected_input_revision': revision, 'changes': profile})
        assert response.status_code == 200, response.text
        response = client.get(path)
        assert response.status_code == 200, response.text
        ranked = response.json()['activities']
        assert {entry['id'] for entry in ranked} == expected_ids
        for entry in ranked:
            for evidence, reason in zip(entry['evidence'], entry['reasons'], strict=True):
                assert evidence['posting_quote'] == entry[evidence['posting_field']]
                assert evidence['matched_term'] in reason
                assert evidence['matched_term'] not in {'있는', '자전거'}
    # A neutral title can qualify only when the acquired body supports the work.
    body = '대여 이력 데이터 분석과 수요 시각화 결과를 제출합니다.'
    fetch.return_value = ([{**postings()[1], 'description_text': body}], sources)
    result = client.get(path).json()['activities']
    assert len(result) == 1
    assert all(e['posting_field'] == 'description_text' and e['posting_quote'] == body for e in result[0]['evidence'])
print('activities API: ownership, goal-only, partial/error isolation, no AI, revision checks passed')

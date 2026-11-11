from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))

from course_groups import GROUPS_BY_CATALOG, grouped_courses, grouped_roadmap
from services.course_recommendations import available_courses, recommend

CATALOG = 'seoultech-cse-2026-major-v1'
KOREAN = 'stcse-2026-ac66832f2c533c700dde1354'
ENGLISH = 'stcse-2026-56e5e2a1aedbfd4d2e87404c'


def rows():
    return [dict(course_id=cid, course_name=name, course_code=None, credits=3, recommended_year=2,
                 recommended_term='2학기', is_completed=False)
            for cid, name in ((KOREAN, '데이터베이스'), (ENGLISH, 'Database'),
                              ('advanced-db', 'Advanced Database'), ('same-name', 'Database'))]


def test_only_explicit_ids_in_the_target_catalog_group():
    original = rows()
    grouped = grouped_courses(original, CATALOG)
    assert len(grouped) == 3
    assert grouped[0]['course_name'] == '데이터베이스 (Database)'
    assert [c['course_name'] for c in grouped[1:]] == ['Advanced Database', 'Database']
    assert grouped_courses(original, 'different-catalog') == original
    assert original == rows()


def test_database_completion_keeps_distinct_advanced_and_same_name_candidates():
    original = rows()
    original[1]['is_completed'] = True
    grouped = grouped_courses(original, CATALOG)
    assert set(available_courses(grouped)) == {'advanced-db', 'same-name'}
    assert [c['course_id'] for c in recommend({}, grouped, 'confirmed',
            lambda *_: [KOREAN, ENGLISH, 'advanced-db', 'same-name'])] == ['advanced-db', 'same-name']


def test_all_groups_have_two_unique_actual_ids_and_distinct_official_codes():
    groups = GROUPS_BY_CATALOG[CATALOG]
    assert len(groups) == 16
    members = [member for group in groups for member in group['members']]
    assert len({member['course_id'] for member in members}) == 32
    assert len({member['course_code'] for member in members}) == 32
    assert all(member['course_id'].startswith('stcse-2026-') for member in members)


def test_grouped_equivalences_preserve_external_substitution_without_self_link():
    original = rows()
    original[0]['verified_equivalent_ids'] = [ENGLISH, 'other-approved-course']
    original[1]['verified_equivalent_ids'] = [KOREAN]
    original[1]['equivalent_completed'] = True
    grouped = grouped_courses(original, CATALOG)
    assert grouped[0]['verified_equivalent_ids'] == ['other-approved-course']
    assert grouped[0]['equivalent_completed']
    assert KOREAN not in available_courses(grouped)


def test_legacy_cards_merge_evidence_and_remap_steps_without_mutation():
    korean, english, *_ = rows()
    korean.update(related_skills=['SQL'], evidence_refs=['ko'])
    english.update(related_skills=['SQL', 'Python'], evidence_refs=['en'])
    original = {'recommended_courses': [english, korean],
                'roadmap': [{'related_course_ids': [ENGLISH, KOREAN]}]}
    before = deepcopy(original)
    result = grouped_roadmap(original, CATALOG)
    assert len(result['recommended_courses']) == 1
    assert set(result['recommended_courses'][0]['related_skills']) == {'SQL', 'Python'}
    assert set(result['recommended_courses'][0]['evidence_refs']) == {'ko', 'en'}
    assert result['roadmap'][0]['related_course_ids'] == [KOREAN]
    assert grouped_roadmap(result, CATALOG) == result
    assert original == before

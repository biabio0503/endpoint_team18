"""Reviewed bilingual identities, scoped to one catalog. Never infer from names.

The first member is the existing Korean course ID used for new selections and
recommendations. Official subject numbers are display/search metadata, not IDs.
"""
import json
from pathlib import Path


_reference = json.loads((Path(__file__).parent / 'data' / 'seoultech_cse_2026_groups.json').read_text())
GROUPS_BY_CATALOG = {_reference['catalog_id']: _reference['groups']}


def group_for(catalog_id, course_id):
    return next((group for group in GROUPS_BY_CATALOG.get(catalog_id, ())
                 if any(member['course_id'] == course_id for member in group['members'])), None)


def member_ids(catalog_id, course_id):
    group = group_for(catalog_id, course_id)
    return [member['course_id'] for member in group['members']] if group else [course_id]


def canonical_id(catalog_id, course_id):
    return member_ids(catalog_id, course_id)[0]


def equivalent_pairs(catalog_id):
    return [tuple(member['course_id'] for member in group['members'])
            for group in GROUPS_BY_CATALOG.get(catalog_id, ())]


def grouped_courses(courses, catalog_id):
    """Collapse before filtering/paging, preserving one course's credits.

This is a read projection only. Existing completion rows and saved AI evidence
are never rewritten. Database substitute relationships do not define UI groups.
"""
    buckets = {}
    for course in courses:
        buckets.setdefault(canonical_id(catalog_id, course['course_id']), []).append(course)
    result = []
    for cid, rows in buckets.items():
        group = group_for(catalog_id, cid)
        course = dict(next((row for row in rows if row['course_id'] == cid), rows[0]))
        if group:
            korean, english = group['members']
            course.update(course_id=cid, course_name=f"{korean['course_name']} ({english['course_name']})",
                          course_code=' / '.join(member['course_code'] for member in group['members']),
                          member_course_ids=[member['course_id'] for member in group['members']],
                          course_group=group['group_number'])
        for field in ('is_completed', 'equivalent_completed'):
            if any(field in row for row in rows):
                course[field] = any(row.get(field, False) for row in rows)
        for field in ('related_skills', 'evidence_refs'):
            if any(field in row for row in rows):
                course[field] = list(dict.fromkeys(item for row in rows for item in row.get(field, [])))
        if any('verified_equivalent_ids' in row for row in rows):
            course['verified_equivalent_ids'] = sorted({canonical_id(catalog_id, other)
                for row in rows for other in row.get('verified_equivalent_ids', [])} - {cid})
        result.append(course)
    return result


def grouped_roadmap(result, catalog_id):
    """Present old English/duplicate cards and both step references without AI."""
    return {**result,
            'recommended_courses': grouped_courses(result['recommended_courses'], catalog_id),
            'roadmap': [{**step, 'related_course_ids': list(dict.fromkeys(
                canonical_id(catalog_id, cid) for cid in step['related_course_ids']))}
                for step in result['roadmap']]}

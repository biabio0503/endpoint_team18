"""Assemble current evidence once and validate every generated reference server-side."""
import json
import re
import unicodedata

from api.domain import FIELDS, payload, json_value
from repositories.courses import CourseRepository
from services.course_recommendations import available_courses, selected_courses, rank_courses
from services.project_experience import current_comparison, digest, model_basis, skill_key
from services.roadmap_validation import invalid, parse_result
from services.job_skill_analysis import ALIASES, skill_priority

RULES_VERSION = 'personalized-roadmap-v10-compound-spans'
TASK_TYPES = {
    'learn': ['practice', 'apply', 'validate', 'document'],
    'deepen': ['apply', 'validate', 'document'],
    'verify_experience': ['verify_experience'],
}
MARKET_LIMIT = '해외 원격근무 채용공고의 제한된 표본입니다. 국내 대학생의 필수 기술이나 학습 우선순위를 뜻하지 않습니다.'


def capture_basis(db, row):
    """Caller holds the owner's plan lock in a consistent DB snapshot. No external I/O."""
    comparison = current_comparison(db, row)
    jobs, project = comparison['job_analysis'], comparison['project_analysis']
    repo = CourseRepository(db)
    catalog = repo.catalog(row['catalog_id']) if row['catalog_id'] else None
    department = repo.department(row['department_id']) if row['department_id'] else None
    valid = bool(catalog and department and catalog['department_id'] == row['department_id']
                 and department['university_id'] == row['university_id'])
    courses = repo.recommendation_courses(row['request_id'], row['catalog_id']) if valid else []
    review_status = payload(row)['review_status'] if valid and courses else 'unavailable'
    refs, skills = {}, []
    for item in comparison['comparisons']:
        name = item['skill_name']
        ref = 'comparison:' + skill_key(name)
        # Compact source quotes only; no original document, file name or job HTML is sent.
        job_refs, project_refs = [], []
        for evidence in item['job_evidence']:
            eid = 'job:' + digest([name, evidence])[:24]
            refs[eid] = {'kind': 'job', 'skill_name': name, **evidence}
            job_refs.append(eid)
        for evidence in item['project_evidence']:
            eid = 'experience:' + evidence['experience_id']
            fields = ('document_id', 'extraction_revision', 'analysis_id', 'experience_id', 'evidence_text',
                      'contribution_scope', 'user_answer', 'match_source', 'activity', 'role', 'output')
            refs[eid] = {'kind': 'project', 'skill_name': name, **{k: evidence.get(k) for k in fields}}
            project_refs.append(eid)
        refs[ref] = {'kind': 'comparison', 'skill_name': name, 'student_status': item['student_status'],
                     'reason': item['reason'], 'job_refs': job_refs, 'project_refs': project_refs}
        skills.append({k: item[k] for k in ('skill_name', 'category', 'student_status', 'reason', 'job_requirement', 'skill_answer')} |
                      {'comparison_ref': ref, 'job_refs': job_refs, 'project_refs': project_refs})
    limits = [MARKET_LIMIT, '경험 확인이나 작업 완료는 기술 숙련도를 보증하지 않습니다.']
    if jobs.get('sample_notice'):
        limits.append(jobs['sample_notice'])
    if jobs.get('previous_analysis_version'):
        limits.append('이전 기준의 직무 분석입니다. 직무 역량 비교에서 분석을 다시 실행하면 개선된 공고·기술 기준을 적용합니다.')
    if not jobs.get('snapshot_id') or not focused_skills({'skills': skills}):
        limits.append('검증된 직무 기술 근거가 없어 기술별 준비 상태는 판단하지 않았습니다. 수강 후보는 진로 목표·교육과정 기준입니다.')
    elif jobs['status'] != 'success':
        limits.append('직무 분석이 일부 미완료되어 검증된 기술과 근거만 사용했습니다.')
    if project['status'] != 'success':
        limits.append('프로젝트 분석 자료가 없거나 일부 미완료입니다. 확인되지 않은 경험은 경험 없음으로 판단하지 않습니다.')
    if review_status == 'unavailable':
        limits.append('사용할 수 있는 현재 과목 목록이 없어 수강 후보를 제공할 수 없습니다.')
    elif review_status == 'unconfirmed':
        limits.append('이수 선택 확인 전입니다. 선택하지 않은 과목은 미이수로 확정하지 않으며 잠정 후보로 제시합니다.')
    elif review_status == 'partial':
        limits.append('현재 과목 목록에 누락이 있다고 보고되었습니다. 이수 확인 범위는 현재 목록에 한정됩니다.')
    if catalog and catalog['completeness_status'] != 'complete':
        limits.append('과목 목록의 완전성이 확인되지 않았습니다. 전체 학업 이력을 나타내지 않습니다.')
    basis = {'rules_version': RULES_VERSION, 'model_name': model_basis(), 'input_revision': row['input_revision'],
             'profile': {k: row[k] for k in FIELDS}, 'catalog': dict(catalog) if valid else None,
             'courses': courses, 'review_status': review_status,
             'course_selection_revision': row['course_selection_revision'],
             'reviewed_catalog_id': row['reviewed_catalog_id'], 'reviewed_selection_revision': row['reviewed_selection_revision'],
             'reviewed_at': row['reviewed_at'], 'reported_missing_courses': bool(row['reported_missing_courses']),
             'outside_completed_courses': repo.outside(row['request_id'], row['catalog_id']),
             'job_snapshot_id': jobs.get('snapshot_id'), 'job_status': jobs['status'],
             'job_analysis_outdated': jobs.get('previous_analysis_version', False),
             'job_analyzed_at': jobs.get('saved_at'), 'job_summary': jobs.get('analysis_summary', {}),
             'document_basis': project['document_basis'], 'project_version': project['analysis_version'],
             'project_status': project['status'],
             'project_documents': [{k: d[k] for k in ('document_id', 'extraction_revision', 'analysis_id', 'status', 'limitations')}
                                   for d in project['documents']],
             'excluded_documents': [{k: d[k] for k in ('document_id', 'extraction_revision', 'reason')}
                                    for d in project['excluded_documents']],
             'skills': skills, 'evidence': refs, 'limitations': limits}
    basis['generation_mode'] = 'ai' if basis['job_snapshot_id'] and focused_skills(basis) else 'limited_guidance'
    if basis['generation_mode'] == 'limited_guidance':
        basis['model_name'] = 'server-guidance-v1'
    # Stable JSON types across SQLite and PostgreSQL (Decimal/datetime included).
    return json.loads(json.dumps(basis, ensure_ascii=False, default=json_value))


def focused_skills(basis):
    eligible = [s for s in basis['skills'] if s.get('job_requirement', {}).get('recommendation_eligible', True)]
    # Legacy snapshots keep their recorded order; new evidence has explicit ranking fields.
    if any('supporting_job_count' in s.get('job_requirement', {}) for s in eligible):
        eligible.sort(key=lambda s: skill_priority({**s['job_requirement'], 'name': s['skill_name']}, s['student_status']))
    known = [s for s in eligible if s['student_status'] in ('no_experience', 'confirmed_experience')]
    unknown = [s for s in eligible if s['student_status'] not in ('no_experience', 'confirmed_experience')]
    return known[:12] + unknown[:3]


def excluded_named_skills(basis, focused):
    included = {skill_key(s['skill_name']) for s in focused}
    # Generic competencies (e.g. data analysis) are ordinary activity prose too.
    # This check covers named technologies in the verified comparison, not an
    # unbounded natural-language/unknown-technology classifier.
    return [s['skill_name'] for s in basis['skills'] if skill_key(s['skill_name']) not in included
            and s.get('category') not in ('technical_competency', 'other')]


def named_skill_pattern(name):
    aliases = ALIASES.get(skill_key(name), (name, None, (name,)))[2]
    # ASCII token boundaries allow Korean particles (Pandas로), but do not merge
    # Java/JavaScript or SQL/PostgreSQL. Mask allowed full names before this check.
    terms = sorted((re.escape(unicodedata.normalize('NFKC', a)) for a in aliases), key=len, reverse=True)
    return re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(terms) + r')(?![A-Za-z0-9_])', re.I)


def model_input(basis):
    fields = ('course_id', 'course_name', 'course_code', 'description_text', 'category', 'credits', 'recommended_year', 'recommended_term')
    skills, evidence = [], {}
    focused = focused_skills(basis)
    ranked = rank_courses(basis['profile'], basis['courses'], basis['review_status'], basis['skills'])
    originals = available_courses(basis['courses'])
    allowed_courses = {c['course_id']: {**originals[c['course_id']], **c, 'description_text': originals[c['course_id']].get('description_text')} for c in ranked}
    for skill in focused:
        # Counts/status use ALL verified evidence; a small exact-quote sample suffices for generation.
        job_refs = [r for r in skill.get('job_refs', []) if basis['evidence'][r].get('recommendation_eligible', True)]
        item = {**skill, 'job_refs': job_refs[:2], 'project_refs': skill.get('project_refs', [])[:3]}
        item['allowed_action_type'] = 'learn' if skill['student_status'] == 'no_experience' else 'deepen' if skill['student_status'] == 'confirmed_experience' else 'verify_experience'
        item['allowed_task_types'] = TASK_TYPES[item['allowed_action_type']]
        item['action_required_terms'] = ['경험', '확인'] if item['allowed_action_type'] == 'verify_experience' else []
        skills.append(item)
        for ref in [item['comparison_ref'], *item['job_refs'], *item['project_refs']]:
            evidence[ref] = basis['evidence'][ref]
        evidence[item['comparison_ref']] = {**evidence[item['comparison_ref']], 'job_refs': item['job_refs'], 'project_refs': item['project_refs']}
    return {k: basis[k] for k in ('profile', 'review_status', 'limitations', 'job_summary', 'project_status')} | {
        'skills': skills, 'evidence': evidence,
        'allowed_evidence_refs': [s['comparison_ref'] for s in skills],
        'out_of_scope_skill_names': excluded_named_skills(basis, focused),
        'evidence_scope': {'verified_skill_count': len(basis['skills']), 'included_skill_count': len(skills),
                           'selection': 'Role relevance, independent job support, requirement level, then verified experience; up to 12 explicit no-experience/confirmed skills and 3 unverified skills. Context-only evidence is excluded.'},
        'eligible_courses': [{**{k: c.get(k) for k in fields},
                              'recommendation_type': c['recommendation_type'], 'keyword_evidence': c['keyword_evidence'],
                              'verified_equivalent_ids': [cid for cid in c.get('verified_equivalent_ids', []) if cid in allowed_courses]}
                             for c in allowed_courses.values()],
        'completed_courses': [{k: c.get(k) for k in ('course_id', 'course_name')} for c in basis['courses'] if c['is_completed']],
        'catalog': basis['catalog'],
    }


def validate_result(raw, basis):
    result = parse_result(raw)
    sent = model_input(basis)
    skills = {s['skill_name']: s for s in sent['skills']}
    allowed = {c['course_id']: c for c in sent['eligible_courses']}

    def verify_refs(names, refs, location, names_field='related_skills'):
        if len(set(names)) != len(names):
            invalid('skill_duplicate', (*location, names_field))
        for index, name in enumerate(names):
            if name not in skills:
                invalid('skill_not_allowed', (*location, names_field, index, 'skill_name') if names_field == 'skill_targets'
                        else (*location, names_field, index))
        if len(set(refs)) != len(refs):
            invalid('evidence_duplicate', (*location, 'evidence_refs'))
        for index, ref in enumerate(refs):
            if ref not in sent['evidence']:
                invalid('evidence_not_provided', (*location, 'evidence_refs', index))
            if ref not in sent['allowed_evidence_refs']:
                invalid('evidence_ref_not_allowed', (*location, 'evidence_refs', index))
            if sent['evidence'][ref]['skill_name'] not in names:
                invalid('evidence_skill_mismatch', (*location, 'evidence_refs', index))
        if not {skills[n]['comparison_ref'] for n in names}.issubset(refs):
            invalid('evidence_comparison_missing', (*location, 'evidence_refs'))

    course_ids = [c.course_id for c in result.recommended_courses]
    seen_courses = set()
    all_courses = {c['course_id']: c for c in basis['courses']}
    for index, cid in enumerate(course_ids):
        location = ('recommended_courses', index, 'course_id')
        if cid in seen_courses:
            invalid('course_duplicate', location)
        if cid not in allowed:
            course = all_courses.get(cid, {})
            invalid('course_completed' if course.get('is_completed') else
                    'course_equivalent_completed' if course.get('equivalent_completed') else 'course_not_allowed', location)
        if set(allowed[cid].get('verified_equivalent_ids', [])).intersection(seen_courses):
            invalid('course_equivalent_duplicate', location)
        seen_courses.add(cid)
    server_courses = {c['course_id']: c for c in selected_courses(course_ids, basis['courses'], basis['review_status'])}
    if set(server_courses) != set(course_ids):
        invalid('course_selection_mismatch', ('recommended_courses',))
    courses = []
    for index, suggestion in enumerate(result.recommended_courses):
        location = ('recommended_courses', index)
        verify_refs(suggestion.related_skills, suggestion.evidence_refs, location)
        course = allowed[suggestion.course_id]
        description = (course.get('description_text') or '').strip()
        limited = (not description or basis['review_status'] != 'confirmed' or basis['job_status'] != 'success'
                   or basis['project_status'] != 'success' or basis['catalog'].get('completeness_status') != 'complete'
                   or any(skills[n]['student_status'] not in ('no_experience', 'confirmed_experience') for n in suggestion.related_skills))
        courses.append({**suggestion.model_dump(), **server_courses[suggestion.course_id],
                        'description_text': description or None, 'description_basis': 'description' if description else 'name_inference',
                        'recommendation_confidence': 'limited' if limited else suggestion.recommendation_confidence,
                        'availability_status': 'not_verified', 'source': basis['catalog'],
                        'recommendation_kind': 'opinion',
                        'limitations': '과목명 기반 추론입니다. 실제 강의 내용을 확인해 주세요.' if not description else '설명과의 관련성에 대한 추천 의견입니다.',
                        'availability_notice': '교육과정 수강 후보입니다. 실제 개설·수강 가능 여부·졸업요건·공식 선수과목은 학교에서 확인해 주세요.'})
    seen_steps, seen_tasks, seen_actions, steps = set(), set(), set(), []
    for order, step in enumerate(result.roadmap, 1):
        location = ('roadmap', order - 1)
        if step.step_id in seen_steps:
            invalid('step_id_duplicate', (*location, 'step_id'))
        if step.order != order:
            invalid('step_order_invalid', (*location, 'order'))
        if len(set(step.depends_on)) != len(step.depends_on):
            invalid('dependency_duplicate', (*location, 'depends_on'))
        for index, dependency in enumerate(step.depends_on):
            if dependency not in seen_steps:
                invalid('dependency_not_previous', (*location, 'depends_on', index))
        if len(set(step.related_course_ids)) != len(step.related_course_ids):
            invalid('related_course_duplicate', (*location, 'related_course_ids'))
        for index, cid in enumerate(step.related_course_ids):
            if cid not in course_ids:
                invalid('related_course_not_recommended', (*location, 'related_course_ids', index))
        names = [s.skill_name for s in step.skill_targets]
        verify_refs(names, step.evidence_refs, location, 'skill_targets')
        intents = {t.action_type for t in step.skill_targets}
        if len(intents) != 1:
            invalid('step_action_types_mixed', (*location, 'skill_targets'))
        for index, target in enumerate(step.skill_targets):
            status = skills[target.skill_name]['student_status']
            expected_action = 'deepen' if status == 'confirmed_experience' else 'learn' if status == 'no_experience' else 'verify_experience'
            if target.student_status != status:
                invalid('experience_status_mismatch', (*location, 'skill_targets', index, 'student_status'))
            if target.action_type != expected_action:
                invalid('experience_action_mismatch', (*location, 'skill_targets', index, 'action_type'))
        for index, cid in enumerate(step.related_course_ids):
            suggested = next(c for c in courses if c['course_id'] == cid)
            if not set(names).intersection(suggested['related_skills']):
                invalid('related_course_skill_mismatch', (*location, 'related_course_ids', index))
        for index, task in enumerate(step.tasks):
            task_location = (*location, 'tasks', index)
            if 'verify_experience' in intents:
                if task.task_type != 'verify_experience':
                    invalid('task_type_mismatch', (*task_location, 'task_type'))
                if '경험' not in task.action or '확인' not in task.action:
                    invalid('experience_verification_wording', (*task_location, 'action'))
            if 'deepen' in intents and task.task_type == 'practice':
                invalid('confirmed_experience_basic_practice', (*task_location, 'task_type'))
            if task.task_type not in TASK_TYPES[next(iter(intents))]:
                invalid('task_type_mismatch', (*task_location, 'task_type'))
            for field in ('title', 'action', 'completion_criteria', 'deliverable'):
                if re.search(r'교과목|강의|수강', getattr(task, field)):
                    invalid('task_course_claim', (*task_location, field))
            action = ' '.join(task.action.casefold().split())
            if task.task_id in seen_tasks:
                invalid('task_id_duplicate', (*task_location, 'task_id'))
            if action in seen_actions:
                invalid('task_action_duplicate', (*task_location, 'action'))
            seen_tasks.add(task.task_id)
            seen_actions.add(action)
        seen_steps.add(step.step_id)
        steps.append({**step.model_dump(), 'related_skills': names, 'recommendation_kind': 'opinion'})

    excluded_patterns = [named_skill_pattern(n) for n in sent['out_of_scope_skill_names']]
    included_patterns = [named_skill_pattern(n) for n in sorted(skills, key=len, reverse=True)]
    prose_fields = {'title', 'purpose', 'reason', 'personalization_reason', 'limitations',
                    'action', 'completion_criteria', 'deliverable'}

    def check_prose(value, location=()):
        if isinstance(value, dict):
            for key, item in value.items():
                check_prose(item, (*location, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                check_prose(item, (*location, index))
        elif isinstance(value, str):
            if re.search(r'최우선|반드시|역량 부족|필수 역량|필수 기술|미흡', value):
                invalid('prohibited_expression', location)
            if location[-1] in prose_fields:
                remaining = unicodedata.normalize('NFKC', value)
                for pattern in included_patterns:
                    remaining = pattern.sub(' ', remaining)
                if any(pattern.search(remaining) for pattern in excluded_patterns):
                    invalid('skill_not_allowed_in_prose', location)

    # Course prose is discarded and replaced with source-grounded server text.
    check_prose({'roadmap': result.model_dump()['roadmap']})
    summary = {key: [s['skill_name'] for s in basis['skills'] if s['student_status'] in states] for key, states in (
        ('confirmed_skills', {'confirmed_experience'}),
        ('skills_to_verify', {'document_supported', 'needs_confirmation', 'not_verified'}),
        ('learning_candidates', {'no_experience'}))}
    # These statuses/summary are computed by the server, never accepted from Gemini.
    partial = basis['job_status'] != 'success' or basis['project_status'] != 'success' or basis['review_status'] != 'confirmed'
    scope = {'verified_skill_count': len(basis['skills']), 'included_skills': [s['skill_name'] for s in focused_skills(basis)]}
    original_courses = {c['course_id']: c for c in basis['courses']}
    ranked_courses = [{**c, 'source': basis['catalog'],
                       'description_text': original_courses[c['course_id']].get('description_text') or None}
                      for c in rank_courses(basis['profile'], basis['courses'], basis['review_status'], basis['skills'])]
    valid_ids = {c['course_id'] for c in ranked_courses}
    for step in steps:
        step['related_course_ids'] = [cid for cid in step['related_course_ids'] if cid in valid_ids]
    return {'status': 'partial' if partial else 'success', 'career_goal': basis['profile']['career_goal'],
            'target_role': basis['profile']['target_role'], 'preparation_summary': summary,
            'preparation_items': basis['skills'], 'evidence': basis['evidence'],
            'recommended_courses': ranked_courses, 'roadmap': steps, 'limitations': basis['limitations'], 'generation_scope': scope,
            'course_status': 'catalog_unavailable' if basis['review_status'] == 'unavailable' else 'provisional' if basis['review_status'] == 'unconfirmed' else 'available',
            'basis': {k: basis[k] for k in ('catalog', 'review_status', 'course_selection_revision', 'reviewed_at',
                'outside_completed_courses', 'job_snapshot_id', 'job_status', 'job_analyzed_at', 'job_summary',
                'project_status', 'project_version', 'project_documents', 'excluded_documents', 'document_basis')}}

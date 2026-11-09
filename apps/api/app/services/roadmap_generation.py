"""Assemble current evidence once and validate every generated reference server-side."""
import json
import re
from pydantic import ValidationError

from api.domain import FIELDS, payload, json_value
from repositories.courses import CourseRepository
from services.course_recommendations import available_courses, selected_courses
from services.gemini import GeminiError
from services.project_experience import current_comparison, digest, model_basis, skill_key
from services.roadmap_schemas import GeneratedRoadmap

RULES_VERSION = 'personalized-roadmap-v1'
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
    courses = repo.courses(row['request_id'], row['catalog_id'], include_description=True) if valid else []
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
    if jobs['status'] != 'success':
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
             'job_analyzed_at': jobs.get('saved_at'), 'job_summary': jobs.get('analysis_summary', {}),
             'document_basis': project['document_basis'], 'project_version': project['analysis_version'],
             'project_status': project['status'],
             'project_documents': [{k: d[k] for k in ('document_id', 'extraction_revision', 'analysis_id', 'status', 'limitations')}
                                   for d in project['documents']],
             'excluded_documents': [{k: d[k] for k in ('document_id', 'extraction_revision', 'reason')}
                                    for d in project['excluded_documents']],
             'skills': skills, 'evidence': refs, 'limitations': limits}
    # Stable JSON types across SQLite and PostgreSQL (Decimal/datetime included).
    return json.loads(json.dumps(basis, ensure_ascii=False, default=json_value))


def focused_skills(basis):
    known = [s for state in ('no_experience', 'confirmed_experience') for s in basis['skills'] if s['student_status'] == state]
    unknown = [s for s in basis['skills'] if s['student_status'] not in ('no_experience', 'confirmed_experience')]
    return known[:12] + unknown[:3]


def model_input(basis):
    fields = ('course_id', 'course_name', 'course_code', 'description_text', 'category', 'credits', 'recommended_year', 'recommended_term')
    skills, evidence = [], {}
    focused = focused_skills(basis)
    for skill in focused:
        # Counts/status use ALL verified evidence; a small exact-quote sample suffices for generation.
        item = {**skill, 'job_refs': skill.get('job_refs', [])[:2], 'project_refs': skill.get('project_refs', [])[:3]}
        item['allowed_action_type'] = 'learn' if skill['student_status'] == 'no_experience' else 'deepen' if skill['student_status'] == 'confirmed_experience' else 'verify_experience'
        skills.append(item)
        for ref in [item['comparison_ref'], *item['job_refs'], *item['project_refs']]:
            evidence[ref] = basis['evidence'][ref]
        evidence[item['comparison_ref']] = {**evidence[item['comparison_ref']], 'job_refs': item['job_refs'], 'project_refs': item['project_refs']}
    return {k: basis[k] for k in ('profile', 'review_status', 'limitations', 'job_summary', 'project_status')} | {
        'skills': skills, 'evidence': evidence,
        'evidence_scope': {'verified_skill_count': len(basis['skills']), 'included_skill_count': len(skills),
                           'selection': 'Up to 12 explicit no-experience/confirmed skills and 3 unverified skills; counts use all evidence, quotes are sampled.'},
        'eligible_courses': [{k: c.get(k) for k in fields} for c in available_courses(basis['courses']).values()],
        'completed_courses': [{k: c.get(k) for k in ('course_id', 'course_name')} for c in basis['courses'] if c['is_completed']],
        'catalog': basis['catalog'],
    }


def invalid():
    raise GeminiError('gemini_invalid_response', '생성된 추천의 과목·경험 상태·근거 또는 실행 순서를 검증하지 못했습니다.')


def validate_result(raw, basis):
    try:
        result = GeneratedRoadmap.model_validate(raw.model_dump() if isinstance(raw, GeneratedRoadmap) else raw)
    except (ValidationError, TypeError, ValueError):
        invalid()
    skills = {s['skill_name']: s for s in basis['skills']}
    allowed = available_courses(basis['courses'])

    def verify_refs(names, refs):
        if len(set(names)) != len(names) or not set(names).issubset(skills):
            invalid()
        if len(set(refs)) != len(refs) or not set(refs).issubset(basis['evidence']):
            invalid()
        if not {skills[n]['comparison_ref'] for n in names}.issubset(refs):
            invalid()
        if any(basis['evidence'][r]['skill_name'] not in names for r in refs):
            invalid()

    course_ids = [c.course_id for c in result.recommended_courses]
    if len(set(course_ids)) != len(course_ids) or not set(course_ids).issubset(allowed):
        invalid()
    server_courses = {c['course_id']: c for c in selected_courses(course_ids, basis['courses'], basis['review_status'])}
    courses = []
    for suggestion in result.recommended_courses:
        verify_refs(suggestion.related_skills, suggestion.evidence_refs)
        course = allowed[suggestion.course_id]
        description = (course.get('description_text') or '').strip()
        if (description and suggestion.course_evidence not in description) or (not description and suggestion.course_evidence != course['course_name']):
            invalid()
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
        if step.order != order or step.step_id in seen_steps or not set(step.depends_on).issubset(seen_steps):
            invalid()
        if len(set(step.depends_on)) != len(step.depends_on) or len(set(step.related_course_ids)) != len(step.related_course_ids):
            invalid()
        if not set(step.related_course_ids).issubset(course_ids):
            invalid()
        names = [s.skill_name for s in step.skill_targets]
        verify_refs(names, step.evidence_refs)
        intents = {t.action_type for t in step.skill_targets}
        if len(intents) != 1:
            invalid()
        for target in step.skill_targets:
            status = skills[target.skill_name]['student_status']
            expected_action = 'deepen' if status == 'confirmed_experience' else 'learn' if status == 'no_experience' else 'verify_experience'
            if target.student_status != status or target.action_type != expected_action:
                invalid()
        for cid in step.related_course_ids:
            suggested = next(c for c in courses if c['course_id'] == cid)
            if not set(names).intersection(suggested['related_skills']):
                invalid()
        for task in step.tasks:
            if 'verify_experience' in intents and (task.task_type != 'verify_experience' or '경험' not in task.action or '확인' not in task.action):
                invalid()
            if 'deepen' in intents and task.task_type == 'practice':
                invalid()
            # Curriculum IDs are displayed separately. Activities may not invent
            # lectures, taught content, or enrollment availability in free text.
            prose = ' '.join((task.title, task.action, task.completion_criteria, task.deliverable))
            if re.search(r'교과목|강의|수강', prose):
                invalid()
            action = ' '.join(task.action.casefold().split())
            if task.task_id in seen_tasks or action in seen_actions:
                invalid()
            seen_tasks.add(task.task_id)
            seen_actions.add(action)
        seen_steps.add(step.step_id)
        steps.append({**step.model_dump(), 'related_skills': names, 'recommendation_kind': 'opinion'})
    prose = json.dumps(result.model_dump(), ensure_ascii=False)
    if re.search(r'최우선|반드시|역량 부족|필수 역량|필수 기술|미흡', prose):
        invalid()
    summary = {key: [s['skill_name'] for s in basis['skills'] if s['student_status'] in states] for key, states in (
        ('confirmed_skills', {'confirmed_experience'}),
        ('skills_to_verify', {'document_supported', 'needs_confirmation', 'not_verified'}),
        ('learning_candidates', {'no_experience'}))}
    # These statuses/summary are computed by the server, never accepted from Gemini.
    partial = basis['job_status'] != 'success' or basis['project_status'] != 'success' or basis['review_status'] != 'confirmed'
    scope = {'verified_skill_count': len(basis['skills']), 'included_skills': [s['skill_name'] for s in focused_skills(basis)]}
    return {'status': 'partial' if partial else 'success', 'career_goal': basis['profile']['career_goal'],
            'target_role': basis['profile']['target_role'], 'preparation_summary': summary,
            'preparation_items': basis['skills'], 'evidence': basis['evidence'],
            'recommended_courses': courses, 'roadmap': steps, 'limitations': basis['limitations'], 'generation_scope': scope,
            'course_status': 'catalog_unavailable' if basis['review_status'] == 'unavailable' else 'provisional' if basis['review_status'] == 'unconfirmed' else 'available',
            'basis': {k: basis[k] for k in ('catalog', 'review_status', 'course_selection_revision', 'reviewed_at',
                'outside_completed_courses', 'job_snapshot_id', 'job_status', 'job_analyzed_at', 'job_summary',
                'project_status', 'project_version', 'project_documents', 'excluded_documents', 'document_basis')}}

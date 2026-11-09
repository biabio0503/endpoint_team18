"""Current document evidence, source checks, and deterministic experience comparison."""
import hashlib
import json
import os
import re
import uuid

from repositories.documents import DocumentRepository
from repositories.experience_analysis import AnalysisRepository, decode
from services.gemini import GeminiError
from services.gemini_projects import extract_project_experiences
from services.job_skill_analysis import normalize_skill, _key, _skill_in_quote

MAX_PROJECT_CHARS = 60000
PROJECT_VERSION = 'project-experience-v1'
JOB_VERSION = 'job-skills-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def model_basis():
    return os.environ.get('GEMINI_MODEL', '').strip() or 'gemini-3.5-flash'


def project_version():
    return PROJECT_VERSION + ':' + model_basis()


def job_basis(row):
    return digest([JOB_VERSION, model_basis(), row['career_goal'], row['target_role']])


def skill_key(name):
    return _key(normalize_skill(name, 'other')[0])


def documents_for_analysis(db, rid):
    """Only called after plan ownership is verified, within the same transaction."""
    repo = DocumentRepository(db)
    eligible, excluded, basis = [], [], []
    for row in repo.list_active(rid):
        doc = dict(row)
        revision = doc['extraction_revision']
        extraction = repo.extraction(doc['document_id'], revision) if revision and revision > 0 else None
        text = extraction['extracted_text'] if extraction else None
        reason = None
        if doc['extraction_status'] not in ('ready', 'partial'):
            reason = doc['extraction_status']
        elif doc['extraction_status'] == 'partial' and not doc['partial_confirmed_at']:
            reason = 'partial_unconfirmed'
        elif not extraction or extraction['extraction_status'] != doc['extraction_status']:
            reason = 'invalid_extraction'
        elif not text or not text.strip():
            reason = 'empty_text'
        basis.append([doc['document_id'], revision, doc['extraction_status'], bool(doc['partial_confirmed_at']), digest(text)])
        meta = {k: doc[k] for k in ('document_id', 'extraction_revision', 'original_filename', 'extraction_status')}
        if reason:
            excluded.append({**meta, 'reason': reason})
        else:
            eligible.append({**meta, 'extracted_text': text, 'segments': decode(extraction['segments']),
                             'limitations': decode(extraction['limitations'])})
    return eligible, excluded, digest(basis)


def verify_experiences(document, extraction, analysis_id):
    if extraction.document_id != document['document_id']:
        return [], [{'code': 'unexpected_document_id'}]
    if extraction.extraction_revision != document['extraction_revision']:
        return [], [{'code': 'extraction_revision_mismatch'}]
    verified, errors, seen = [], [], set()
    for item in extraction.experiences:
        start = document['extracted_text'].find(item.evidence_text)
        if start < 0:
            errors.append({'code': 'evidence_not_in_source'})
            continue
        # Korean postpositions may directly follow an English technology name.
        quote_for_names = re.sub(r'(?<=[A-Za-z0-9])(?=[가-힣])', ' ', item.evidence_text)
        if not _skill_in_quote(item.skill_name, quote_for_names):
            errors.append({'code': 'skill_not_in_evidence'})
            continue
        if any(value is not None and value not in item.evidence_text for value in (item.role, item.output)):
            errors.append({'code': 'role_or_output_not_in_evidence'})
            continue
        name, category = normalize_skill(item.skill_name, item.category)
        identity = (skill_key(name), start, item.evidence_text, item.activity)
        if identity in seen:
            continue
        seen.add(identity)
        end = start + len(item.evidence_text)
        scope = item.contribution_scope
        # A model's personal label alone is not a contribution check. Named team
        # members cannot be mapped to the uploader. The user can clarify later.
        if scope == 'personal' and not re.search(r'\bI\s|\bmy\s|나는|내가|제가|저는|본인은|본인이', item.evidence_text, re.I):
            scope = 'unknown'
        verified.append({**item.model_dump(), 'skill_name': name, 'category': category,
                         'model_contribution_scope': item.contribution_scope, 'contribution_scope': scope,
                         'experience_id': str(uuid.uuid4()), 'analysis_id': analysis_id,
                         'document_id': document['document_id'], 'extraction_revision': document['extraction_revision'],
                         'evidence_start': start, 'evidence_end': end, 'evidence_verified': True,
                         'locations': [s for s in document['segments'] if s['start'] < end and s['end'] > start]})
    return verified, errors


def analyze_document(document):
    result = {'analysis_id': str(uuid.uuid4()), 'status': 'error', 'experiences': [], 'errors': []}
    if len(document['extracted_text']) > MAX_PROJECT_CHARS:
        result['errors'] = [{'code': 'document_too_long'}]
        return result
    try:
        extraction = extract_project_experiences(document)
    except GeminiError as exc:
        result['errors'] = [{'code': exc.code, 'message': exc.message}]
        return result
    verified, errors = verify_experiences(document, extraction, result['analysis_id'])
    result.update(experiences=verified, errors=errors,
                  status='partial' if errors and verified else 'error' if errors else 'success')
    return result


def current_project(db, rid, revision):
    documents, excluded, basis = documents_for_analysis(db, rid)
    repo = AnalysisRepository(db)
    saved = repo.analyses(rid, project_version())
    answers = repo.answers(rid)
    records, experiences, errors = [], [], []
    for doc in documents:
        stored = saved.get((doc['document_id'], doc['extraction_revision']))
        result = decode(stored['result_json']) if stored else {'status': 'not_started', 'experiences': [], 'errors': []}
        records.append({k: doc[k] for k in ('document_id', 'extraction_revision', 'original_filename', 'limitations')} |
                       {'status': result['status'], 'analysis_id': stored['analysis_id'] if stored else None,
                        'analyzed_input_revision': stored['input_revision'] if stored else None,
                        'errors': result['errors']})
        errors.extend({**e, 'document_id': doc['document_id']} for e in result['errors'])
        for item in result['experiences']:
            answer = answers.get(item['experience_id'])
            user = ({'status': answer['status'], 'correction': answer['correction'],
                     'input_revision': answer['input_revision'], 'updated_at': answer['updated_at'], 'source': 'user'}
                    if answer else None)
            experiences.append({**item, 'original_filename': doc['original_filename'], 'user_answer': user,
                                'analyzed_input_revision': stored['input_revision'],
                                'source': 'document_ai', 'user_confirmation': user['status'] if user else None})
    analyzed = sum(r['status'] in ('success', 'partial') for r in records)
    status = ('no_documents' if not documents else 'success'
              if analyzed == len(documents) and not errors and not excluded else 'partial'
              if analyzed else 'error' if errors else 'not_started')
    return {'status': status, 'input_revision': revision, 'document_basis': basis,
            'analysis_version': project_version(), 'analyzed_documents': analyzed,
            'eligible_documents': len(documents), 'verified_experiences': len(experiences),
            'documents': records, 'excluded_documents': excluded, 'experiences': experiences, 'errors': errors}


def job_snapshot_payload(snapshot, revision):
    return {**decode(snapshot['result_json']), 'snapshot_id': snapshot['snapshot_id'],
            'basis_key': snapshot['basis_key'], 'analyzed_input_revision': snapshot['input_revision'],
            'input_revision': revision, 'saved_at': snapshot['created_at'], 'reused': True}


def compare_skill(experiences, answer=None):
    positives, negatives = [], []
    for e in experiences:
        user = e['user_answer']
        if not user:
            continue
        if user['status'] == 'confirmed' or (user['status'] == 'corrected' and user['correction']['contribution_scope'] == 'personal'):
            positives.append(e)
        if user['status'] == 'no_experience':
            negatives.append(e)
    if answer and answer['status'] == 'no_experience':
        negatives.append(answer)
    if positives and negatives:
        return 'needs_confirmation', '사용자 답변이 서로 달라 경험 여부를 다시 확인해 주세요.'
    if positives:
        return 'confirmed_experience', '사용자가 직접 수행한 경험으로 확인했습니다. 숙련도를 보증하지는 않습니다.'
    if negatives:
        return 'no_experience', '사용자가 이 기술의 수행 경험이 없다고 답했습니다.'
    if answer and answer['status'] == 'unknown':
        return 'needs_confirmation', '사용자가 경험 여부 판단을 보류했습니다.'
    if any(not e['user_answer'] and e['contribution_scope'] == 'personal' for e in experiences):
        return 'document_supported', '문서에 개인 수행 표현이 있으나 사용자 확인 전입니다.'
    if experiences:
        return 'needs_confirmation', '팀 기술 또는 수행 주체 미확인 항목입니다. 본인의 수행 여부를 확인해 주세요.'
    return 'not_verified', '현재 제공된 자료에서 수행 근거를 찾지 못했습니다. 경험이 없다는 뜻은 아닙니다.'


def current_comparison(db, row):
    repo = AnalysisRepository(db)
    project = current_project(db, row['request_id'], row['input_revision'])
    snapshot = repo.job(row['request_id'], job_basis(row))
    jobs = job_snapshot_payload(snapshot, row['input_revision']) if snapshot else {'status': 'not_started', 'skills': []}
    answers = repo.skill_answers(snapshot['snapshot_id'], project['document_basis']) if snapshot else {}
    comparisons = []
    for skill in jobs['skills']:
        key = skill_key(skill['name'])
        evidence = []
        for item in project['experiences']:
            user = item['user_answer']
            effective = user['correction']['skill_name'] if user and user['status'] == 'corrected' else item['skill_name']
            if skill_key(effective) == key:
                evidence.append({**item, 'effective_skill_name': normalize_skill(effective, item['category'])[0],
                                 'match_source': 'user_correction' if user and user['status'] == 'corrected' else 'document_ai'})
        answer = answers.get(key)
        status, reason = compare_skill(evidence, answer)
        comparisons.append({'skill_name': skill['name'], 'category': skill['category'], 'student_status': status,
                            'reason': reason, 'preparation_candidate': 'consider_learning' if status == 'no_experience'
                            else 'experience_confirmed' if status == 'confirmed_experience' else 'verify_experience_first',
                            'job_requirement': {k: v for k, v in skill.items() if k not in ('name', 'category', 'evidence')},
                            'project_evidence': evidence, 'job_evidence': skill['evidence'],
                            'skill_answer': ({'status': answer['status'], 'updated_at': answer['updated_at'], 'source': 'user'} if answer else None)})
    return {'status': 'success' if jobs['status'] == project['status'] == 'success' else 'partial' if snapshot else 'error',
            'input_revision': row['input_revision'], 'career_goal': row['career_goal'], 'target_role': row['target_role'],
            'job_analysis': jobs, 'project_analysis': project, 'comparisons': comparisons}

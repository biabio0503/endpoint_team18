"""Offline replay against any PYTHONPATH app tree. No API, DB or paid model calls."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from services import himalayas as h, job_skill_analysis as a
from services.job_skill_schemas import BatchExtraction, RoleInterpretation
from services.project_experience import compare_skill, verify_experiences
from services.project_experience_schemas import DocumentExperience
from services.roadmap_generation import model_input, validate_result

FIXTURE = json.loads(Path(__file__).with_name('cases.json').read_text())


def replay(role_id):
    role = FIXTURE['roles'][role_id]
    posts = [{**p, 'guid': 'https://himalayas.app/companies/fixture/jobs/' + p['id'], 'seniority': ['Entry-level']}
             for p in FIXTURE['jobs']]
    by_id = {p['guid']: p for p in posts}
    posts += [p for p in posts if p['id'] in FIXTURE['duplicate_ids']]
    interpretation = RoleInterpretation.model_validate({'status':'success', 'canonical_role':role['target'],
        'clarification_message':None, 'search_keywords':[{'keyword':k,'relation':r} for k,r in role['keywords']]})
    def extract(jobs):
        return BatchExtraction.model_validate({'jobs':[{'job_id':j['id'], 'skills':by_id[j['id']]['extracted_skills']} for j in jobs]})
    with patch.object(a, 'generate_job_keywords', return_value=interpretation), \
         patch.object(h, '_request_page', side_effect=lambda keyword,page: {'jobs':posts if page == 1 else []}), \
         patch.object(a, 'extract_job_skills', side_effect=extract):
        result = a.analyze_job_skills(role['goal'], role['target'])
    expected = {p['id'] for p in FIXTURE['jobs'] if p['expected'][role_id]['include']}
    selected = {j['job_id'].rsplit('/',1)[-1] for j in result['job_analyses']}
    skills = result['skills']
    core = [s for s in skills if s.get('recommendation_eligible', True)]
    top = core[:5]
    duplicates = len(skills) - len({s['name'].casefold().replace(' ', '') for s in skills})
    metrics = {'selected_count':len(selected), 'selected_ids':sorted(selected), 'expected_count':len(expected),
        'false_positive_ids':sorted(selected - expected), 'false_negative_ids':sorted(expected - selected),
        'top5':[s['name'] for s in top], 'top5_appropriate':sum(s['name'] in role['appropriate'] for s in top),
        'top5_denominator':len(top), 'duplicate_names':duplicates,
        'all_skills':[s['name'] for s in skills], 'core_skills':[s['name'] for s in core],
        'counts':{s['name']:s['mentioned_job_count'] for s in skills}, 'sample_notice':result.get('sample_notice')}
    return result, metrics


def personalization(analysis, scenario):
    """A fixed, transparent provider stub tests the production prompt contract and validator.
    It is not an evaluation of Gemini's wording or course-choice quality.
    """
    experiences=[]
    if scenario in ('document_only','confirmed'):
        doc={'document_id':'fixture-doc','extraction_revision':1,'extracted_text':'I used SQL to analyze sales data.', 'segments':[]}
        response=DocumentExperience.model_validate({'document_id':'fixture-doc','extraction_revision':1,'experiences':[
            {'skill_name':'SQL','category':'database_query_language','activity':'analyze sales data',
             'contribution_scope':'personal','evidence_text':doc['extracted_text']}]})
        experiences,errors=verify_experiences(doc,response,'fixture-analysis')
        assert not errors
        for e in experiences:e['user_answer']={'status':'confirmed'} if scenario=='confirmed' else None
    skills=[]; refs={}
    for s in analysis['skills']:
        status,reason=compare_skill(experiences if s['name']=='SQL' else [],
                                   {'status':'no_experience'} if scenario=='no_experience' and s['name']=='SQL' else None)
        ref='comparison:'+s['name']
        skills.append({'skill_name':s['name'],'student_status':status,'reason':reason,'comparison_ref':ref,
                       'job_requirement':{k:v for k,v in s.items() if k not in ('name','evidence')},'job_refs':[],'project_refs':[]})
        refs[ref]={'skill_name':s['name']}
    basis={'skills':skills,'evidence':refs,'profile':{'career_goal':'데이터 분석','target_role':'Data Analyst'},
        'courses':FIXTURE['course_catalog'],'review_status':'confirmed','catalog':{'completeness_status':'complete'},
        'job_status':'success','project_status':'success','limitations':[],'job_summary':analysis['analysis_summary'],
        'course_selection_revision':1,'reviewed_at':'fixture','outside_completed_courses':[],'job_snapshot_id':'fixture',
        'job_analyzed_at':'fixture','project_version':'fixture','project_documents':[],'excluded_documents':[], 'document_basis':'fixture'}
    data=model_input(basis)
    sql=next(s for s in data['skills'] if s['skill_name']=='SQL')
    intent=sql['allowed_action_type']
    # Fixed response per state: candidate is provisional when experience is unverified.
    cid='sql-advanced' if intent=='deepen' else 'sql-intro'
    course=next(c for c in data['eligible_courses'] if c['course_id']==cid)
    raw={'recommended_courses':[{'course_id':cid,'related_skills':['SQL'],'evidence_refs':[sql['comparison_ref']],
        'course_evidence':course['description_text'],'reason':'SQL 분석 관련 과목','personalization_reason':sql['student_status'],
        'course_role':'advanced' if intent=='deepen' else 'foundation','recommendation_confidence':'limited'}],
        'roadmap':[{'step_id':'step-1','order':1,'title':'SQL 프로젝트 확인','purpose':'분석 근거 정리','reason':sql['student_status'],
        'skill_targets':[{'skill_name':'SQL','student_status':sql['student_status'],'action_type':intent}],
        'related_course_ids':[cid],'depends_on':[],'evidence_refs':[sql['comparison_ref']],'limitations':'합성 fixture',
        'tasks':[{'task_id':'task-1','task_type':'verify_experience' if intent=='verify_experience' else 'apply',
        'title':'SQL 기록','action':'SQL 경험 확인 자료를 정리한다.' if intent=='verify_experience' else 'SQL 분석 결과를 검증한다.' if intent=='deepen' else 'SQL 조회 예제를 작성한다.',
        'completion_criteria':'쿼리와 검토 기록','deliverable':'SQL 기록 파일'}]}]}
    result=validate_result(raw,basis)
    return {'status':sql['student_status'],'action_type':intent,'activity':result['roadmap'][0]['tasks'][0]['action'],
        'courses':[c['course_id'] for c in result['recommended_courses']],
        'eligible_courses':[c['course_id'] for c in data['eligible_courses']],
        'focused_skills':[s['skill_name'] for s in data['skills']]}


def evaluate():
    results={key:replay(key) for key in FIXTURE['roles']}
    return {'scope':FIXTURE['scope'],'roles':{key:metrics for key,(_,metrics) in results.items()},
            'personalization':{case:personalization(results['data'][0],case) for case in ('absent','document_only','confirmed','no_experience')}}

if __name__=='__main__':
    value=evaluate()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    else:print(json.dumps(value,ensure_ascii=False,indent=2))

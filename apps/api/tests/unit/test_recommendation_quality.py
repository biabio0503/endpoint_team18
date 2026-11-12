"""Fixed, human-labeled occupation/evidence fixtures; all provider output is frozen."""
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from services import himalayas as h, job_skill_analysis as a
from services.job_skill_schemas import ExtractedSkill
from services.job_relevance import source_segments
from services.roadmap_generation import focused_skills, validate_result
from services.gemini import GeminiError

spec = importlib.util.spec_from_file_location('quality_replay', Path(__file__).parents[1] / 'fixtures/recommendation-quality/evaluate.py')
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


@pytest.mark.parametrize('role', replay.FIXTURE['roles'])
def test_labeled_selection_and_top_five(role):
    result, metrics = replay.replay(role)
    assert metrics['false_positive_ids'] == []
    assert metrics['false_negative_ids'] == []
    assert metrics['top5_appropriate'] == metrics['top5_denominator'] == 5
    assert metrics['duplicate_names'] == 0
    assert result['sample_notice'] and str(metrics['selected_count']) in result['sample_notice']
    assert result['analysis_version'] == a.ANALYSIS_VERSION
    assert len(result['selection_summary']['decisions']) == len(replay.FIXTURE['jobs'])
    for job in result['job_analyses']:
        assert job['source_url'].startswith('https://himalayas.app/')
    for skill in result['skills']:
        assert skill['mentioned_job_count'] <= metrics['selected_count']
        assert sum(skill[k] for k in ('required_job_count','preferred_job_count','mentioned_only_job_count','unknown_job_count')) == skill['mentioned_job_count']
        if skill['mentioned_job_count'] == 1:
            assert skill['single_job_notice'] and skill['evidence'][0]['source_url']


def test_company_context_not_recommended_but_manufacturing_duties_preserved():
    data, _ = replay.replay('data')
    skills = {s['name']:s for s in data['skills']}
    assert not skills['CISSP']['recommendation_eligible']
    # CAD is NOT globally forbidden in analyst jobs: two real analysis duties survive.
    assert skills['CAD']['supporting_job_count'] == 2
    assert skills['CAD']['mentioned_job_count'] == 3  # includes one transparent company mention
    assert skills['CAD']['supporting_direct_job_count'] == 0
    assert not next(e for e in skills['CAD']['evidence'] if e['job_id'].endswith('/data-a'))['recommendation_eligible']
    manufacturing, _ = replay.replay('manufacturing')
    specialized = {s['name']:s for s in manufacturing['skills']}
    for name in ('CAD','CATIA','SolidWorks'):
        assert specialized[name]['recommendation_eligible']
    assert specialized['CATIA']['preferred_job_count'] == 1
    assert specialized['SolidWorks']['preferred_job_count'] == 1


def verified(text, name, quote, kind='required', category='other'):
    return a.verify_skills({'description_text':text}, [ExtractedSkill(name=name,category=category,requirement_type=kind,evidence_text=quote)])


@pytest.mark.parametrize('heading,expected', [('Requirements','required'),('Preferred','preferred'),('Responsibilities','unknown'),('About the company','mentioned')])
def test_requirement_heading_is_read_from_source_even_outside_model_quote(heading,expected):
    result,rejected=verified(heading+'\nSQL proficiency.','SQL','SQL proficiency.')
    assert not rejected and result[0]['requirement_type']==expected
    assert result[0]['recommendation_eligible'] == (heading!='About the company')


def test_quote_cannot_borrow_mandatory_label_and_known_tool_cannot_bypass_name_check():
    text='Requirements\nPython is required.\nAbout the company\nOur customers use CAD.'
    result,_=verified(text,'CAD',text)
    assert not result[0]['recommendation_eligible'] and result[0]['requirement_type']=='mentioned'
    assert verified('Python is required.','CAD','Python is required.',category='technical_competency')[1][0]['reason']=='skill_not_in_evidence'
    result,_=verified('No CAD is required.','CAD','No CAD is required.')
    assert not result[0]['recommendation_eligible']


@pytest.mark.parametrize('heading', [
    'What you’ll do', "What you'll do", 'WHAT YOU’LL DO:',
    '## What You’ll Do', '**What you’ll do**', 'What you\u00a0will do',
    'What you‘ll do', 'What youʼll do', 'What you’ll be doing',
])
def test_typographic_duty_heading_ends_company_context_without_changing_source(heading):
    quote = 'Build SQL dashboards from sales data.'
    text = f'About us\nWe are a retailer.\n{heading}\n{quote}\nPreferred\nCAD is a plus.'
    segments = list(source_segments(text))
    assert [s['section'] for s in segments] == ['context', 'context', 'duty', 'duty', 'preferred', 'preferred']
    assert all(text[s['start']:s['end']].strip() == s['text'] for s in segments)
    result, rejected = verified(text, 'SQL', quote, kind='mentioned')
    assert not rejected
    assert result[0]['evidence_section'] == 'duty'
    assert result[0]['recommendation_eligible'] is True
    assert result[0]['requirement_type'] == 'mentioned'
    assert text[result[0]['evidence_start']:result[0]['evidence_end']] == quote
    keywords = [{'keyword': 'Data Analyst', 'relation': 'direct'}]
    job = h.normalize_job({'guid': 'fixture', 'title': 'Data Analyst', 'description': text}, 'Data Analyst', keywords)
    assert job['relevance']['core_families'] == ['data']


@pytest.mark.parametrize('quote', [
    'No CAD experience is required, but SQL proficiency is required.',
    'SQL proficiency is required, but no CAD experience is required.',
    'CAD experience is not required, but SQL proficiency is required.',
    'We do not require CAD experience; SQL proficiency is required.',
    'We don’t require CAD experience, whereas SQL proficiency is required.',
    'No CAD experience is required, SQL proficiency is required.',
    'SQL proficiency is required and CAD experience is not required.',
    'CAD and CATIA experience are not required; SQL proficiency is required.',
])
def test_requirement_negation_applies_only_to_the_named_skill_and_clause(quote):
    text = 'Requirements\n' + quote
    results = {}
    for name in ('CAD', 'SQL'):
        items, rejected = verified(text, name, quote)
        assert not rejected
        results[name] = items[0]
        assert text[items[0]['evidence_start']:items[0]['evidence_end']] == quote
    assert results['CAD']['recommendation_eligible'] is False
    assert results['CAD']['requirement_type'] == 'mentioned'
    assert results['SQL']['recommendation_eligible'] is True
    assert results['SQL']['requirement_type'] == 'required'


def test_shared_negative_skill_list_and_positive_alias_keep_their_own_requirement():
    quote = 'No CAD or CATIA experience is required, but PowerBI proficiency is required.'
    text = 'Requirements\n' + quote
    for name in ('CAD', 'CATIA'):
        items, _ = verified(text, name, quote)
        assert items[0]['recommendation_eligible'] is False
    items, _ = verified(text, 'Power BI', quote)
    assert items[0]['recommendation_eligible'] is True
    assert items[0]['requirement_type'] == 'required'


def test_short_quote_cannot_drop_source_negation_or_borrow_another_occurrence():
    text = 'Requirements\nNo CAD experience is required, but SQL proficiency is required. CAD is required for a separate task.'
    for name, quote, eligible, kind in (
        ('CAD', 'CAD experience', False, 'mentioned'),
        ('SQL', 'SQL proficiency', True, 'required'),
        ('CAD', 'CAD is required for a separate task.', True, 'required'),
    ):
        items, rejected = verified(text, name, quote)
        assert not rejected
        assert items[0]['recommendation_eligible'] is eligible
        assert items[0]['requirement_type'] == kind
        assert text[items[0]['evidence_start']:items[0]['evidence_end']] == quote


def test_aliases_identity_requirement_counts_and_distinct_products():
    text='Requirements\nPowerBI, Microsoft Power BI, SQL, PostgreSQL, Java, JavaScript, CAD and AutoCAD.'
    names=['PowerBI','Power BI','Microsoft Power BI','SQL','Postgres','Java','JavaScript','CAD','AutoCAD']
    skills=[]
    for name in names:
        verified_items,rejected=verified(text,name,text)
        assert not rejected
        skills+=verified_items
    job={'job_id':'same','title':'Data Analyst','source_url':'https://himalayas.app/companies/fixture/jobs/same',
         'match_type':'direct','seniority_group':'entry','status':'success','verified_skills':skills}
    output=a.aggregate_skills([job,deepcopy(job)])
    assert {s['name'] for s in output}=={'Power BI','SQL','PostgreSQL','Java','JavaScript','CAD','AutoCAD'}
    assert all(s['mentioned_job_count']==s['required_job_count']==1 and s['mention_frequency']==1 for s in output)
    from datetime import datetime,timezone
    keywords=[{'keyword':'Data Analyst','relation':'direct'}]
    normalized=h.normalize_job({'guid':job['source_url'],'title':job['title'],'description':text},'Data Analyst',keywords)
    selected,_=h.select_jobs([normalized,deepcopy(normalized)],keywords,20,datetime.now(timezone.utc))
    assert len(selected)==1


def test_fixed_project_changes_actions_and_courses_without_inventing_experience():
    result,_=replay.replay('data')
    variants={s:replay.personalization(result,s) for s in ('absent','document_only','confirmed','no_experience')}
    assert variants['absent']['status']=='not_verified'
    assert variants['document_only']['status']=='document_supported'
    assert variants['confirmed']['action_type']=='deepen'
    assert variants['no_experience']['action_type']=='learn'
    # Evidence-based ranking is server-owned and cannot invent a course match
    # solely from the student's experience status.
    assert variants['confirmed']['courses'] == variants['absent']['courses']
    for v in variants.values():
        assert 'completed' not in v['eligible_courses'] and 'equivalent' not in v['eligible_courses']
        assert not {'CAD','CATIA','SolidWorks','CISSP'} & set(v['focused_skills'])


def test_priority_reflects_evidence_then_confirmed_project_and_context_is_ineligible():
    common={'supporting_direct_job_count':1,'supporting_job_count':2,'supporting_required_job_count':1,'supporting_preferred_job_count':0}
    skills=[{'skill_name':name,'student_status':state,'job_requirement':{**common,'recommendation_eligible':eligible}}
            for name,state,eligible in [('A','not_verified',True),('B','confirmed_experience',True),('C','no_experience',False)]]
    assert [s['skill_name'] for s in focused_skills({'skills':skills})]==['B','A']
    assert a.skill_priority(common,'confirmed_experience') < a.skill_priority(common,'not_verified')


def test_generated_output_must_stay_inside_actual_focus():
    from test_roadmap_generation import basis, output
    b=basis()
    b['skills'][0]['job_requirement']={'recommendation_eligible':False}
    with pytest.raises(GeminiError):validate_result(output(),b)


def test_unrelated_model_keyword_cannot_override_target_and_core_duties():
    from datetime import datetime,timezone
    keywords=[{'keyword':'Data Analyst','relation':'direct'}, {'keyword':'Mechanical Design Engineer','relation':'related'},
              {'keyword':'Security Analyst','relation':'related'}]
    target=h.target_context('Analyze sales data','Data Analyst',keywords)
    posts=[p for p in replay.FIXTURE['jobs'] if p['id'] in ('mechanical','security','data-a')]
    jobs=[h.normalize_job({**p,'guid':'https://himalayas.app/companies/fixture/jobs/'+p['id']},keywords[0]['keyword'],keywords,target) for p in posts]
    selected,summary=h.select_jobs(jobs,keywords,20,datetime.now(timezone.utc))
    assert [j['title'] for j in selected]==['Junior Data Analyst']
    assert summary['excluded_by_reason']['core_duties_mismatch']==2


def test_legacy_answer_identity_is_not_rewritten_by_new_alias():
    from services.project_experience import snapshot_skill_key
    assert snapshot_skill_key({},'PowerBI')=='powerbi'
    assert snapshot_skill_key({},'Power BI')=='power bi'
    assert snapshot_skill_key({'analysis_version':a.ANALYSIS_VERSION},'PowerBI')=='power bi'

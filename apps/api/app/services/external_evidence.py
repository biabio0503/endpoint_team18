"""Validate source-provided fragments without interpreting their meaning."""
from datetime import datetime

ALLOWED_FIELDS={
 'job_posting':{'job_role','career_level','required_skills','preferred_skills'},
 'competition':{'organizer','activity_details','eligibility','team_condition','deliverables'},
 'extracurricular':{'organizer','activity_details','eligibility','team_condition','deliverables'},
}

def validate(e):
    if e.kind not in ALLOWED_FIELDS or not e.source_key or e.status not in ('ready','partial') or not e.source_text.strip() or not e.raw:
        raise ValueError('invalid_evidence')
    if e.content_type not in ('text/html; charset=utf-8','application/pdf') or e.recruitment.get('observed_status') not in ('open','closed','unknown'):
        raise ValueError('invalid_evidence')
    observed=datetime.fromisoformat(e.observed_at)
    if observed.tzinfo is None:raise ValueError('invalid_evidence_time')
    if not set(e.facts).issubset(ALLOWED_FIELDS[e.kind]):raise ValueError('invalid_fact_kind')
    segments={}
    for segment in e.segments:
        key=segment['segment_id'];start=segment['start'];end=segment['end']
        if not isinstance(key,str) or key in segments or type(start) is not int or type(end) is not int or not 0<=start<end<=len(e.source_text) or e.source_text[start:end]!=segment['excerpt']:
            raise ValueError('invalid_segment')
        segments[key]=segment
    def check_refs(items):
        if not isinstance(items,list):raise ValueError('invalid_fact')
        for item in items:
            segment=segments.get(item['segment_id'])
            if not segment or item['text']!=segment['excerpt']:raise ValueError('invalid_fact')
    for values in e.facts.values():check_refs(values)
    status_evidence=e.recruitment.get('status_evidence',[])
    check_refs(status_evidence);check_refs(e.recruitment.get('period_evidence',[]))
    if e.recruitment.get('observed_status')!='unknown' and not status_evidence:raise ValueError('missing_status_evidence')

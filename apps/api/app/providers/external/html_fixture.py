"""Parser for explicitly annotated local HTML fixtures, not a live-site scraper."""
from html.parser import HTMLParser
from .models import Evidence

FIELDS={'job_role','career_level','required_skills','preferred_skills','organizer','activity_details','eligibility','team_condition','deliverables','recruitment_period','recruitment_status','title'}
PARSER_VERSION='fixture-html-v1'
class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.parts=[];self.segments=[];self.fields={};self.ignored=0;self.images=False;self.omitted=False;self.length=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style','head'):self.ignored+=1;return
        if self.ignored:return
        if tag=='img':self.images=True
        if tag in ('p','li','h1','h2','h3'):
            self.stack.append({'tag':tag,'id':attrs.get('id'),'field':attrs.get('data-field'),'chunks':[]})
    def handle_data(self,data):
        if not self.ignored:
            if self.stack:self.stack[-1]['chunks'].append(data)
            elif data.strip():self.omitted=True
    def handle_endtag(self,tag):
        if tag in ('script','style','head') and self.ignored:self.ignored-=1;return
        if self.ignored or not self.stack or self.stack[-1]['tag']!=tag:return
        block=self.stack.pop();text=' '.join(''.join(block['chunks']).split())
        if not text:return
        if self.parts:self.parts.append('\n');self.length+=1
        start=self.length;self.parts.append(text);self.length+=len(text);key=f'seg-{len(self.segments)+1:04d}'
        self.segments.append({'segment_id':key,'excerpt':text,'start':start,'end':start+len(text),'html_id':block['id'] or None,'paragraph':len(self.segments)+1})
        if block['field'] in FIELDS:self.fields.setdefault(block['field'],[]).append({'text':text,'segment_id':key})

def parse(item,raw):
    text=raw.decode('utf-8');parser=Parser();parser.feed(text);parser.close()
    source=''.join(parser.parts)
    if not source.strip():raise ValueError('empty_html_text')
    fields=parser.fields;title=(fields.get('title') or [{}])[0].get('text')
    allowed={'job_posting':{'job_role','career_level','required_skills','preferred_skills'},'competition':{'organizer','activity_details','eligibility','team_condition','deliverables'},'extracurricular':{'organizer','activity_details','eligibility','team_condition','deliverables'}}[item['kind']]
    facts={k:v for k,v in fields.items() if k in allowed}
    statuses=fields.get('recruitment_status',[]); state='unknown'
    if len(statuses)==1:state={'모집 중':'open','모집 종료':'closed'}.get(statuses[0]['text'],'unknown')
    recruitment={'observed_status':state,'status_evidence':statuses,'period_evidence':fields.get('recruitment_period',[]),'normalized_deadline':None,'timezone':None,'precision':'unknown'}
    limitations=[]
    if parser.images:limitations.append('이미지의 내용은 추출하지 않았습니다.')
    if parser.omitted:limitations.append('지원하지 않는 HTML 구조의 일부 텍스트를 추출하지 않았습니다.')
    if not title:limitations.append('표시 제목을 확인하지 못했습니다.')
    return Evidence(item['id'],item['kind'],item['url'],'text/html; charset=utf-8',raw,title,source,parser.segments,facts,recruitment,'partial' if limitations else 'ready',limitations,PARSER_VERSION)

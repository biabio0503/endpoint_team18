"""Evaluate unseen fictional inputs. Structural checks are not a quality review."""
import argparse
import json
import time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from prompt import make_prompt

cases = [
    {'career_goal':'UX 디자이너를 준비하고 싶다','target_role':'UX 디자이너','preparation_weeks':5,'course_history_status':'unknown','completed_courses':[],'documents':[{'document_id':'eval-design','extraction_status':'ready','extracted_text':'프로젝트: 독서 앱. 사용자 인터뷰를 진행하고 화면 시안을 만들었습니다.'}]},
    {'career_goal':'데이터 분석을 배우고 싶다','target_role':None,'preparation_weeks':7,'course_history_status':'none','completed_courses':[],'documents':[{'document_id':'eval-data','extraction_status':'ready','extracted_text':'도서 대출 현황을 표로 정리했습니다. 구체적인 담당 역할은 기록되지 않았습니다.'}]},
    {'career_goal':'웹 개발 취업','target_role':'프론트엔드 개발자','preparation_weeks':3,'course_history_status':'provided','completed_courses':[{'course_name':'자료구조','credits':3}],'documents':[{'document_id':'eval-web','extraction_status':'ready','extracted_text':'학교 행사 안내 웹페이지에서 HTML로 일정 목록을 만들었습니다.'}]}
]
p = argparse.ArgumentParser(); p.add_argument('--model', required=True); p.add_argument('--output', required=True); args = p.parse_args()
if not torch.cuda.is_available(): raise RuntimeError('CUDA 필요')
tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, dtype=torch.float16, device_map='cuda')
results = []
for case in cases:
    prompt = tok.apply_chat_template([{'role':'user','content':make_prompt(case)}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tok(prompt, return_tensors='pt').to('cuda'); started = time.monotonic()
    with torch.inference_mode(): output = model.generate(**inputs, max_new_tokens=600, do_sample=False, pad_token_id=tok.eos_token_id)
    answer = tok.decode(output[0][inputs['input_ids'].shape[-1]:], skip_special_tokens=True).strip()
    row = {'case': case['documents'][0]['document_id'], 'seconds': round(time.monotonic()-started,2), 'valid_json':False, 'schema':False, 'evidence':False, 'weeks':False}
    try:
        obj=json.loads(answer); row['valid_json']=True
        text = lambda v: isinstance(v,str) and bool(v.strip())
        row['schema']=isinstance(obj,dict) and text(obj.get('summary')) and all(isinstance(obj.get(k),list) for k in ('experiences','questions','roadmap','course_suggestions','limitations')) and bool(obj.get('roadmap'))
        if row['schema']:
            row['schema']=all(all(text(e.get(k)) for k in ('project','description','document_id','quote')) for e in obj['experiences'] if isinstance(e,dict)) and all(isinstance(e,dict) for e in obj['experiences']) and all(all(text(v) for v in obj[k]) for k in ('questions','course_suggestions','limitations')) and all(isinstance(s,dict) and text(s.get('goal')) and text(s.get('reason')) and isinstance(s.get('actions'),list) and bool(s['actions']) and all(text(a) for a in s['actions']) for s in obj['roadmap'])
            row['evidence']=bool(obj['experiences']) and all(isinstance(e,dict) and e.get('document_id')==case['documents'][0]['document_id'] and isinstance(e.get('quote'),str) and bool(e['quote'].strip()) and e['quote'] in case['documents'][0]['extracted_text'] for e in obj['experiences'])
            row['weeks']=all(isinstance(s,dict) and type(s.get('start_week')) is int and type(s.get('end_week')) is int and 1 <= s['start_week'] <= s['end_week'] <= case['preparation_weeks'] for s in obj['roadmap'])
    except (ValueError, TypeError, KeyError): pass
    row['output_preview']=answer[:400]
    results.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
with open(args.output,'w',encoding='utf-8') as f: json.dump({'model':args.model,'results':results},f,ensure_ascii=False,indent=2)

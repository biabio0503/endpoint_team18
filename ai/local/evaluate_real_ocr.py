"""Compare local OCR models on a small, fixed public KDoc benchmark subset.

Text-present checks only: whitespace and Unicode normalization, exact matching.
This is not full CER, official benchmark scoring, or a representative sample.
"""
import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ai'))
from local.ocr import LocalOCR, MAX_PIXELS
import pypdfium2 as pdfium
from huggingface_hub import hf_hub_download

parser=argparse.ArgumentParser()
parser.add_argument('--candidate', help='실험 인식기 경로. 지정 시 해당 모델만 평가')
parser.add_argument('--padding',type=int,default=0)
parser.add_argument('--layout',choices=['rows','columns','auto'],default='rows')
parser.add_argument('--orientation',choices=['none','auto'],default='none')
parser.add_argument('--split',choices=['validation','holdout','final'],default='validation')
parser.add_argument('--output',default='ai/local/ocr-real-evaluation.json')
args=parser.parse_args()
REPO='ONTHEIT/KDoc-OCRBench-V2'; base=ROOT/'ai/local/data/kdoc'
for name in ('licenses.csv','categories.jsonl','text_present.jsonl'):
    hf_hub_download(REPO,name,repo_type='dataset',local_dir=base)
with (base/'licenses.csv').open(encoding='utf-8-sig',newline='') as f:
    licenses={r['filename']:r for r in csv.DictReader(f)}
with (base/'categories.jsonl').open(encoding='utf-8') as f:
    categories=[json.loads(line) for line in f if line.strip()]
tests=defaultdict(list)
with (base/'text_present.jsonl').open(encoding='utf-8') as f:
    for line in f:
        row=json.loads(line); txt=row.get('text') or ''
        if row.get('checked')=='verified' and row.get('page')==1 and 8<=len(txt)<=60:
            tests[row['pdf']].append(row)
chosen=[]
for category in ('Notices','Manuals','Reports'):
    matches=sorted([x['pdf'] for x in categories if x['category']==category and x['pdf'] in licenses and len(tests[x['pdf']])>=8])
    if not matches: raise RuntimeError(f'조건에 맞는 문서 없음: {category}')
    filename=matches[{'validation':0,'holdout':1,'final':2}[args.split]]
    hf_hub_download(REPO,'pdfs/'+filename,repo_type='dataset',local_dir=base)
    chosen.append((category,filename,tests[filename][:8]))
def norm(text): return re.sub(r'\s+','',unicodedata.normalize('NFKC',text)).casefold()
results=[]
for provider in (('candidate',) if args.candidate else ('open-source','local')):
    engine=LocalOCR('local' if provider=='candidate' else provider, recognition_path=args.candidate if provider=='candidate' else None, crop_padding=args.padding, layout=args.layout, orientation=args.orientation)
    for category,name,items in chosen:
        doc=pdfium.PdfDocument(str(base/'pdfs'/name)); page=doc[0]
        try:
            w,h=page.get_size(); scale=min(2.0,(MAX_PIXELS/(w*h))**0.5)
            image=page.render(scale=scale).to_pil(); extracted=norm(engine.read_image(image))
        finally: page.close(); doc.close()
        passed=sum(norm(x['text']) in extracted for x in items)
        info=licenses[name]
        row={'model':provider,'category':category,'document':name,'license':info['license'],'source_url':info['source_url'],'attribution':info['attribution'],'checks':len(items),'passed':passed}
        results.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
report={'dataset':REPO,'split':args.split,'padding':args.padding,'layout':args.layout,'orientation':args.orientation,'candidate':args.candidate,'selection':'sorted eligible documents: validation index 0, development index 1, final index 2; first 8 verified checks per document','method':'exact substring after NFKC, whitespace removal and case folding; stricter than benchmark tolerance, no table or reading-order checks','results':results}
out=Path(args.output); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

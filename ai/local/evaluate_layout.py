import argparse, json, sys, time, unicodedata
from pathlib import Path
from PIL import Image

def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1): new.append(min(new[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]

parser=argparse.ArgumentParser(description='Compare auto layout with saved student-project OCR predictions; never overwrites benchmark data.')
parser.add_argument('--dataset',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
base=args.dataset.resolve()
if args.output.exists(): raise FileExistsError('Output already exists; select a new file.')
sys.path.insert(0,str(root/'ai'))
sys.path.insert(0,str(base))
from local.ocr import LocalOCR
from score_facts import score_facts
manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
engine=LocalOCR('local',layout='auto')
out=[]
for sample in manifest['samples']:
    image=base/sample['image']; t=time.perf_counter()
    with Image.open(image) as im: candidate=engine.read_image(im)
    baseline=(base/'results/predictions'/f"{sample['id']}.txt").read_text(encoding='utf-8')
    gt=(base/sample['ground_truth']).read_text(encoding='utf-8')
    facts=json.loads((base/sample['facts']).read_text(encoding='utf-8'))
    def score(text):
        norm=lambda x:''.join(c for c in unicodedata.normalize('NFC',x) if not c.isspace())
        ref=norm(gt); hyp=norm(text); scores=score_facts(text,facts)
        return {'errors':distance(ref,hyp),'chars':len(ref),'roles':{s:sum(x['state']==s for x in scores if x['category']=='roles') for s in ('preserved','mislinked','missing','indeterminate')}}
    out.append({'id':sample['id'],'layout':sample['layout'],'baseline':score(baseline),'candidate':score(candidate),'seconds':round(time.perf_counter()-t,2),'candidate_text':candidate})
    print(sample['id'],out[-1]['baseline']['errors'],out[-1]['candidate']['errors'],flush=True)
args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

"""Fine-tune the local CTC recognition head on synthetic Korean text lines.

This trains recognition, not page layout detection. Dataset is generated from
the official university department preview; no personal documents are used.
"""
import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from transformers import AutoImageProcessor, AutoModelForTextRecognition

parser=argparse.ArgumentParser()
parser.add_argument('--data',default='ai/local/data/university_departments.csv')
parser.add_argument('--base',default='ai/models/ocr-v2')
parser.add_argument('--output',default='ai/models/ocr-university')
parser.add_argument('--train-count',type=int,default=270)
parser.add_argument('--eval-count',type=int,default=60)
parser.add_argument('--epochs',type=int,default=2)
parser.add_argument('--augment',action='store_true',help='문서형 문구·숫자·구두점의 합성 학습')
args=parser.parse_args()
if not torch.cuda.is_available(): raise RuntimeError('CUDA GPU가 필요합니다.')
base=Path(args.base); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
processor=AutoImageProcessor.from_pretrained(base,local_files_only=True)
char_to_id={c:i for i,c in enumerate(processor.character_list) if len(c)==1 and i!=0}
with open(args.data,encoding='utf-8',newline='') as f:
    texts=sorted({r[k].strip() for r in csv.DictReader(f) for k in ('학교명','학과명')})
texts=[x for x in texts if 3<=len(x)<=22 and all(c in char_to_id for c in x)]
random.Random(42).shuffle(texts)
need=args.train_count+2*args.eval_count
if len(texts)<need: raise RuntimeError('필터를 통과한 문구가 부족합니다.')
train=texts[:args.train_count]; val=texts[args.train_count:args.train_count+args.eval_count]; test=texts[args.train_count+args.eval_count:need]
train_fonts=['C:/Windows/Fonts/malgun.ttf','C:/Windows/Fonts/malgunbd.ttf']
test_font='C:/Windows/Fonts/batang.ttc'
if not all(Path(x).exists() for x in train_fonts+[test_font]): raise RuntimeError('시험용 Windows 글꼴이 필요합니다.')
def image(text,font_path,size):
    font=ImageFont.truetype(font_path,size)
    bounds=font.getbbox(text); width=max(1,bounds[2]-bounds[0]+16); height=max(1,bounds[3]-bounds[1]+12)
    canvas=Image.new('RGB',(width,height),'white')
    ImageDraw.Draw(canvas).text((8-bounds[0],6-bounds[1]),text,font=font,fill='black')
    return canvas
def augment(text,index):
    options=[text, '기간: '+text, '안내: '+text, text+' (2026년)', text+' 10:00~19:00', '※ '+text, text+' / '+text[:4]]
    return options[index % len(options)] if args.augment else text
def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1): nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=nxt
    return row[-1]
model=AutoModelForTextRecognition.from_pretrained(base,local_files_only=True).cuda()
def evaluate(examples,font_path):
    model.eval(); errors=chars=exact=0
    with torch.inference_mode():
        for text in examples:
            inputs=processor(images=image(text,font_path,28),return_tensors='pt')
            prediction=processor.post_process_text_recognition(model(**{k:v.cuda() for k,v in inputs.items()}))[0]['text']
            errors+=distance(text,prediction); chars+=len(text); exact+=int(text==prediction)
    return {'count':len(examples),'character_error_rate':round(errors/max(chars,1),4),'exact_match_rate':round(exact/len(examples),4)}
baseline=evaluate(test,test_font); print('BASELINE',json.dumps(baseline),flush=True)
for param in model.parameters(): param.requires_grad=False
for param in model.head.head.parameters(): param.requires_grad=True
optimizer=torch.optim.AdamW(model.head.head.parameters(),lr=1e-5,weight_decay=0)
loss_fn=torch.nn.CTCLoss(blank=0,zero_infinity=True)
random.seed(42); torch.manual_seed(42); torch.cuda.manual_seed_all(42)
best=None; best_val=float('inf'); best_epoch=0
for epoch in range(args.epochs):
    model.eval(); model.head.head.train(); order=list(train); random.Random(42+epoch).shuffle(order); total=0
    for index,text in enumerate(order):
        text=augment(text,index+epoch)
        if not all(c in char_to_id for c in text): continue
        inputs=processor(images=image(text,train_fonts[index%len(train_fonts)],26+(index%5)),return_tensors='pt')
        pixel=inputs['pixel_values'].cuda()
        with torch.no_grad():
            backbone=model.model(pixel).last_hidden_state
            encoded=model.head.encoder(backbone).last_hidden_state
        logits=model.head.head(encoded).float().log_softmax(-1).transpose(0,1)
        targets=torch.tensor([char_to_id[c] for c in text],dtype=torch.long,device='cuda')
        loss=loss_fn(logits,targets,torch.tensor([logits.shape[0]],dtype=torch.long),torch.tensor([len(targets)],dtype=torch.long))
        optimizer.zero_grad(); loss.backward(); optimizer.step(); total+=loss.item()
    validation=evaluate(val,test_font)
    print('EPOCH',epoch+1,'loss',round(total/len(order),5),'validation',json.dumps(validation),flush=True)
    if validation['character_error_rate']<best_val:
        best_val=validation['character_error_rate']; best_epoch=epoch+1
        best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
model.load_state_dict(best); trained=evaluate(test,test_font)
model.save_pretrained(out); processor.save_pretrained(out)
report={'source':'공공데이터포털 전국대학별학과정보표준데이터 미리보기 499건','source_sha256':hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),'base':str(base),'augmentation':args.augment,'split_seed':42,'train':len(train),'validation':len(val),'test':len(test),'training_fonts':['맑은 고딕','맑은 고딕 Bold'],'heldout_font':'바탕','trained_parameters':'CTC output projection only','best_epoch':best_epoch,'baseline':baseline,'trained':trained,'note':'합성 단일 줄 이미지 평가. 스캔·손글씨·페이지 검출 성능 아님.'}
(out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('RESULT',json.dumps(report,ensure_ascii=False),flush=True)

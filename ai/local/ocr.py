"""Opt-in local OCR. Results remain partial until the user reviews them."""
from io import BytesIO
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MAX_PIXELS = 20_000_000
MAX_IMAGES = 20

def order_boxes(boxes, layout='rows'):
    if layout == 'rows': return sorted(boxes, key=lambda b:(round(b[0][1]/10),b[0][0]))
    if layout != 'columns': raise ValueError('알 수 없는 정렬 방식입니다.')
    def coords(box):
        xs=[p[0] for p in box]; ys=[p[1] for p in box]
        return min(xs),min(ys),max(xs),max(ys)
    def partition(items,depth=0):
        if len(items)<3 or depth>=20: return sorted(items,key=lambda b:(coords(b)[1],coords(b)[0]))
        rects=[coords(b) for b in items]
        heights=sorted(max(1,r[3]-r[1]) for r in rects); median=heights[len(heights)//2]
        def gaps(axis):
            starts=sorted((r[axis],r[axis+2],i) for i,r in enumerate(rects))
            end=starts[0][1]; left={starts[0][2]}; options=[]
            for start,finish,i in starts[1:]:
                gap=start-end
                if gap>0 and len(left)>=2 and len(items)-len(left)>=2:
                    options.append((gap,set(left)))
                end=max(end,finish); left.add(i)
            return options
        xg=gaps(0); yg=gaps(1)
        xbest=max(xg,default=(0,set()),key=lambda t:t[0]); ybest=max(yg,default=(0,set()),key=lambda t:t[0])
        # Vertical cuts require a wider gutter than ordinary word gaps.
        if xbest[0] > 2.0*median:
            cut=xbest
        elif ybest[0] > 0.7*median:
            cut=ybest
        else:
            return sorted(items,key=lambda b:(round(coords(b)[1]/max(median*0.5,1)),coords(b)[0]))
        left=[b for i,b in enumerate(items) if i in cut[1]]
        right=[b for i,b in enumerate(items) if i not in cut[1]]
        return partition(left,depth+1)+partition(right,depth+1)
    return partition(boxes)

def has_column_pairs(boxes, width):
    """Detect repeated side-by-side text; this is a layout heuristic, not attribution."""
    rects = [(min(p[0] for p in box), min(p[1] for p in box),
              max(p[0] for p in box), max(p[1] for p in box)) for box in boxes[:500]]
    pairs = 0
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            left, right = sorted((a, b), key=lambda r: r[0])
            height = min(left[3] - left[1], right[3] - right[1])
            overlap = max(0, min(left[3], right[3]) - max(left[1], right[1]))
            if (height > 0 and overlap / height >= 0.5 and
                    right[0] - left[2] > width * 0.08 and
                    left[0] < width * 0.5 < right[2]):
                pairs += 1
                if pairs >= 3:
                    return True
    return False

class LocalOCR:
    def __init__(self, model='local', recognition_path=None, crop_padding=0, layout='auto', orientation=None):
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection, AutoModelForTextRecognition
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        det = str(ROOT/'ai/models/ocr-detector')
        # 선택: local = 추가 학습 모델, open-source = 원본 Qota-OCR. 둘 다 로컬 실행.
        paths = {'local': ROOT/'ai/models/ocr-v2', 'open-source': ROOT/'ai/models/qota-ocr'}
        if model not in paths: raise ValueError('OCR 모델은 local 또는 open-source여야 합니다.')
        rec_path = Path(recognition_path) if recognition_path is not None else paths[model]
        if not 0 <= crop_padding <= 20: raise ValueError('OCR 여백은 0~20 픽셀이어야 합니다.')
        self.crop_padding = crop_padding
        if layout not in ('rows', 'columns', 'auto'): raise ValueError('알 수 없는 정렬 방식입니다.')
        self.layout = layout
        if orientation is None: orientation='auto' if model=='local' else 'none'
        if orientation not in ('none','auto'): raise ValueError('지원하지 않는 OCR 회전 설정입니다.')
        self.orientation = orientation
        if not rec_path.is_dir(): raise ValueError(f'OCR 모델이 없습니다: {rec_path}')
        rec = str(rec_path)
        self.dp = AutoImageProcessor.from_pretrained(det, local_files_only=True)
        self.dm = AutoModelForObjectDetection.from_pretrained(det, local_files_only=True).to(self.device).eval()
        self.rp = AutoImageProcessor.from_pretrained(rec, local_files_only=True)
        self.rm = AutoModelForTextRecognition.from_pretrained(rec, local_files_only=True).to(self.device).eval()

    def _detect(self, image):
        batch=self.dp(images=image,return_tensors='pt'); sizes=batch.pop('target_sizes')
        output=self.dm(**{k:v.to(self.device) for k,v in batch.items()})
        return self.dp.post_process_object_detection(output,target_sizes=sizes,threshold=0.2,box_threshold=0.45,unclip_ratio=1.4)[0]['boxes'].tolist()

    def _orient(self, image):
        candidates=[]
        for angle in (0,90,180,270):
            rotated=image if angle==0 else image.rotate(angle,expand=True)
            boxes=self._detect(rotated); horizontal=[]
            for box in boxes:
                xs=[x for x,_ in box]; ys=[y for _,y in box]; w=max(xs)-min(xs); h=max(ys)-min(ys)
                if w>h*1.5 and w>30 and h>4: horizontal.append((w*h,(min(xs),min(ys),max(xs),max(ys))))
            candidates.append((angle,rotated,boxes,horizontal))
        maximum=max(len(x[3]) for x in candidates)
        if maximum<4: return candidates[0][1],candidates[0][2]
        eligible=[x for x in candidates if len(x[3])>=maximum*0.8]
        best=None
        for angle,rotated,boxes,horizontal in eligible:
            scores=[]
            for _,bounds in sorted(horizontal,reverse=True)[:12]:
                inp=self.rp(images=rotated.crop(bounds),return_tensors='pt')
                result=self.rp.post_process_text_recognition(self.rm(**{k:v.to(self.device) for k,v in inp.items()}))[0]
                if result['text'].strip(): scores.append(float(result['score']))
            confidence=sum(scores)/len(scores) if scores else 0
            if best is None or confidence>best[0]: best=(confidence,rotated,boxes)
        return best[1],best[2]

    def read_image(self, image):
        if image.width * image.height > MAX_PIXELS: raise ValueError('OCR 이미지가 너무 큽니다.')
        image = image.convert('RGB')
        with self.torch.inference_mode():
            image,boxes = self._orient(image) if self.orientation=='auto' else (image,self._detect(image))
            lines = []
            layout = ('columns' if has_column_pairs(boxes, image.width) else 'rows') if self.layout == 'auto' else self.layout
            for box in order_boxes(boxes,layout)[:500]:
                xs, ys = [x for x,_ in box], [y for _,y in box]
                pad=self.crop_padding
                crop = image.crop((max(0,min(xs)-pad),max(0,min(ys)-pad),min(image.width,max(xs)+pad),min(image.height,max(ys)+pad)))
                if crop.width < 1 or crop.height < 1: continue
                if crop.height >= crop.width * 1.5: crop = crop.rotate(90,expand=True)
                inp = self.rp(images=crop, return_tensors='pt')
                result = self.rp.post_process_text_recognition(self.rm(**{k:v.to(self.device) for k,v in inp.items()}))
                line = result[0]['text'].strip()
                if line: lines.append(line)
            return '\n'.join(lines)

    def extract(self, extension, data):
        from PIL import Image
        pages = []
        if extension in ('png','jpg','jpeg'):
            with Image.open(BytesIO(data)) as im: pages.append((1, self.read_image(im)))
        elif extension == 'pdf':
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(data)
            try:
                if len(document) > MAX_IMAGES: raise ValueError('OCR PDF는 최대 20페이지입니다.')
                for i in range(len(document)):
                    page = document[i]
                    try:
                        width,height = page.get_size()
                        if width * height * 4 > MAX_PIXELS: raise ValueError('OCR 페이지가 너무 큽니다.')
                        pages.append((i+1,self.read_image(page.render(scale=2).to_pil())))
                    finally: page.close()
            finally: document.close()
        elif extension == 'docx':
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = [x for x in archive.namelist() if x.startswith('word/media/') and x.lower().endswith(('.png','.jpg','.jpeg'))]
                if len(names)>MAX_IMAGES: raise ValueError('DOCX OCR 이미지는 최대 20개입니다.')
                for i,name in enumerate(names,1):
                    with Image.open(BytesIO(archive.read(name))) as im: pages.append((i,self.read_image(im)))
        return pages

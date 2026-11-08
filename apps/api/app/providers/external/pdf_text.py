"""Local PDF fixture extraction; no OCR or semantic field inference."""
from io import BytesIO
from pypdf import PdfReader
from .models import Evidence
PARSER_VERSION='fixture-pdf-v1'
def parse(item,raw):
    if not raw.startswith(b'%PDF-'): raise ValueError('invalid_pdf')
    pdf=PdfReader(BytesIO(raw),strict=True)
    if pdf.is_encrypted or len(pdf.pages)>100: raise ValueError('unsupported_pdf')
    pieces=[];segments=[];length=0;limitations=['PDF의 명시 항목은 자동 분류하지 않았습니다.']
    for page_no,page in enumerate(pdf.pages,1):
        text=page.extract_text() or ''
        if not text.strip(): limitations.append(f'{page_no}페이지의 텍스트를 확보하지 못했습니다.');continue
        if pieces:pieces.append('\n');length+=1
        start=length;pieces.append(text);length+=len(text)
        segments.append({'segment_id':f'seg-{len(segments)+1:04d}','excerpt':text,'start':start,'end':length,'page':page_no})
    text=''.join(pieces)
    if not text.strip():raise ValueError('empty_pdf_text')
    return Evidence(item['id'],item['kind'],item['url'],'application/pdf',raw,None,text,segments,{}, {'observed_status':'unknown','status_evidence':[],'period_evidence':[],'normalized_deadline':None,'timezone':None,'precision':'unknown'},'partial',limitations,PARSER_VERSION)

"""Bounded non-AI text extraction. Image content is never interpreted."""
from io import BytesIO
from pathlib import PurePath
import re
import zipfile
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_UNCOMPRESSED=30*1024*1024
MAX_TEXT=1000000
MAX_PAGES=100
MIMES={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','txt':'text/plain; charset=utf-8'}

class InvalidDocument(ValueError): pass

def _docx_zip(data):
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            infos=z.infolist()
            if len(infos)>1000 or sum(i.file_size for i in infos)>MAX_UNCOMPRESSED or any(i.flag_bits&1 for i in infos): raise InvalidDocument('문서 압축 크기 또는 구성 제한을 초과했습니다.')
            names=z.namelist()
            if len(names)!=len(set(names)) or '[Content_Types].xml' not in names or 'word/document.xml' not in names or z.testzip(): raise InvalidDocument('올바르지 않거나 손상된 DOCX 파일입니다.')
            types=z.read('[Content_Types].xml')
            if b'wordprocessingml.document.main+xml' not in types: raise InvalidDocument('DOCX 본문 형식이 아닙니다.')
            return names
    except (zipfile.BadZipFile, RuntimeError, OSError, KeyError) as e: raise InvalidDocument('올바르지 않거나 손상된 DOCX 파일입니다.') from e

def validate_file(name,data):
    if not isinstance(name,str) or not name or len(name)>255 or '/' in name or '\\' in name or any(ord(c)<32 for c in name): raise InvalidDocument('파일 이름을 확인해 주세요.')
    extension=PurePath(name).suffix.lower().lstrip('.')
    if extension not in MIMES: raise InvalidDocument('PDF, DOCX, UTF-8 TXT 파일만 지원합니다.')
    if not data: raise InvalidDocument('빈 파일은 등록할 수 없습니다.')
    try:
        if extension=='txt':
            if data.startswith((b'%PDF-', b'PK\x03\x04')): raise InvalidDocument('파일 내용이 일반 텍스트 형식이 아닙니다.')
            if b'\x00' in data: raise InvalidDocument('텍스트 파일에 지원하지 않는 바이너리 내용이 있습니다.')
            text=data.decode('utf-8-sig')
            if sum(ord(c)<32 and c not in '\r\n\t\f' for c in text)>0: raise InvalidDocument('UTF-8 일반 텍스트 파일이 아닙니다.')
        elif extension=='pdf':
            if not data.startswith(b'%PDF-'): raise InvalidDocument('파일 내용이 PDF 형식이 아닙니다.')
            pdf=PdfReader(BytesIO(data),strict=True)
            if pdf.is_encrypted: raise InvalidDocument('암호화된 PDF는 지원하지 않습니다.')
            if not 0<len(pdf.pages)<=MAX_PAGES: raise InvalidDocument('PDF는 1~100페이지만 지원합니다.')
            for page in pdf.pages: page.get('/Type')
        else:
            _docx_zip(data); Document(BytesIO(data))
    except InvalidDocument: raise
    except Exception as e: raise InvalidDocument('파일 형식이 올바르지 않거나 손상되었습니다.') from e
    return extension,MIMES[extension]

def _pdf_has_image(page):
    try:
        content=page.get_contents()
        if content and any(op == b'INLINE IMAGE' for _, op in content.operations): return True
    except Exception: return True
    visited=set()
    def walk(resources,depth=0):
        if depth>12 or not resources: return False
        try:
            resources=resources.get_object(); objects=resources.get('/XObject')
            if not objects:return False
            objects=objects.get_object()
            for ref in objects.values():
                obj=ref.get_object(); marker=id(obj)
                if marker in visited: continue
                visited.add(marker)
                if obj.get('/Subtype')=='/Image':return True
                if obj.get('/Subtype')=='/Form' and walk(obj.get('/Resources'),depth+1):return True
        except Exception: return True # unreadable resources mean the scope is uncertain
        return False
    return walk(page.get('/Resources'))

def extract(extension,data):
    segments=[]; pieces=[]; limits=[]; offset=0; ocr_needed=False
    def append(text, **location):
        nonlocal offset
        if not text or not text.strip():return
        if pieces: pieces.append('\n'); offset+=1
        if offset+len(text)>MAX_TEXT:
            text=text[:max(0,MAX_TEXT-offset)]; limits.append('텍스트 크기 제한으로 뒷부분을 읽지 못했습니다.')
        if text:
            start=offset; pieces.append(text); offset+=len(text)
            segments.append({'start':start,'end':offset,**location})
    if extension=='txt':
        text=data.decode('utf-8-sig'); append(text,paragraph=1)
    elif extension=='pdf':
        pdf=PdfReader(BytesIO(data),strict=True)
        for idx,page in enumerate(pdf.pages,1):
            try:
                text=page.extract_text() or ''
                if _pdf_has_image(page):
                    ocr_needed=True; limits.append(f'{idx}페이지: 이미지 내용은 읽지 못했습니다.')
                if not text.strip(): limits.append(f'{idx}페이지: 추출된 텍스트가 없어 이미지·빈 페이지 여부 확인이 필요합니다.')
                append(text,page=idx)
            except Exception:
                limits.append(f'{idx}페이지: 텍스트를 읽지 못했습니다.')
    else:
        names=_docx_zip(data); doc=Document(BytesIO(data)); number=0
        def blocks(container):
            nonlocal number
            for block in container.iter_inner_content():
                if isinstance(block,Paragraph):
                    number+=1; append(block.text,paragraph=number)
                elif isinstance(block,Table):
                    for row in block.rows:
                        for cell in row.cells:
                            blocks(cell)
        blocks(doc)
        if any(n.startswith('word/media/') for n in names):
            ocr_needed=True; limits.append('문서에 포함된 이미지의 내용은 읽지 못했습니다.')
        if any(n.startswith(('word/embeddings/','word/charts/','word/diagrams/')) for n in names): limits.append('차트·포함 개체의 내용은 읽지 못할 수 있습니다.')
        if any(re.fullmatch(r'word/(header|footer)\d+\.xml',n) for n in names): limits.append('머리글과 바닥글은 읽은 본문에 포함되지 않습니다.')
        if any(n in names for n in ('word/footnotes.xml','word/endnotes.xml','word/comments.xml')): limits.append('각주·미주·주석은 읽은 본문에 포함되지 않습니다.')
        xml=doc._element.xml
        if any(tag in xml for tag in ('<w:txbxContent','<w:object','<w:altChunk','<w:pict')): limits.append('텍스트 상자 또는 포함 개체의 내용은 읽지 못할 수 있습니다.')
    text=''.join(pieces); limits=list(dict.fromkeys(limits))
    if text.strip(): status='partial' if limits else 'ready'
    else: status='needs_ocr' if ocr_needed else 'failed'
    if status=='failed':limits.append('읽을 수 있는 본문 텍스트가 없습니다.')
    return {'text':text,'segments':segments,'limitations':limits,'status':status,'error_code':'empty_text' if status=='failed' else None}

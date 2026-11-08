"""P3 document API. All operations use the parent plan's session ownership."""
from email.parser import BytesParser
from email.policy import default
import json
import re
import uuid
from config import MAX_DOCUMENT_BYTES, MAX_DOCUMENTS
from providers.document_storage import get_storage
from providers.document_parser import validate_file, InvalidDocument
from worker.documents import timestamp
from repositories.documents import DocumentRepository

MIMES={'application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain; charset=utf-8'}

def request_file(handler,Problem):
    try:
        size=int(handler.headers.get('Content-Length','0'))
        content_type=handler.headers.get('Content-Type','')
        if size<=0 or size>MAX_DOCUMENT_BYTES+65536: raise Problem(413,'too_large','파일 크기 제한을 초과했습니다.')
        if not content_type.lower().startswith('multipart/form-data;'):raise ValueError
        raw=handler.rfile.read(size)
        if len(raw)!=size:raise ValueError
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
        if not message.is_multipart():raise ValueError
        fields={}
        for part in message.iter_parts():
            key=part.get_param('name',header='content-disposition')
            if key not in ('file','expected_input_revision') or key in fields or part.is_multipart():raise ValueError
            fields[key]=part
        if set(fields)!={'file','expected_input_revision'}:raise ValueError
        filename=fields['file'].get_filename(); data=fields['file'].get_payload(decode=True)
        revision_text=fields['expected_input_revision'].get_content().strip()
        if not re.fullmatch(r'0|[1-9][0-9]*',revision_text):raise ValueError
        if data is None:raise ValueError
        if len(data)>MAX_DOCUMENT_BYTES:raise Problem(413,'too_large','파일 크기 제한을 초과했습니다.')
        _,mime=validate_file(filename,data)
        return filename,data,mime,int(revision_text)
    except Problem:raise
    except InvalidDocument as e:raise Problem(422,'invalid_file',str(e)) from e
    except Exception as e:raise Problem(400,'invalid_multipart','파일 업로드 요청 형식을 확인해 주세요.') from e

def summary(row):
    eligible=row['extraction_status']=='ready' or (row['extraction_status']=='partial' and row['partial_confirmed_at'] is not None)
    return {k:row[k] for k in ('document_id','original_filename','mime_type','file_size_bytes','extraction_status','extraction_revision','extraction_error_code','partial_confirmed_at','created_at')} | {'analysis_eligible':eligible}

def check_revision(body,row,Problem):
    if set(body)!={'expected_input_revision'} or type(body.get('expected_input_revision')) is not int or body['expected_input_revision']<0:raise Problem(422,'validation_error','입력 버전을 확인해 주세요.')
    if body['expected_input_revision']!=row['input_revision']:raise Problem(409,'revision_conflict','입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')

def route(handler,db,repo,owner,path,method,Problem):
    match=re.fullmatch(r'/api/roadmap-inputs/([0-9a-f-]{36})/documents(?:/([0-9a-f-]{36})(?:/(retry-extraction|extractions/([0-9]+)(/confirmation)?))?)?',path)
    if not match:return False
    rid,did,action,revision,confirmation=match.groups()
    documents=DocumentRepository(db)
    valid=(not did and method in ('GET','POST')) or (did and not action and method=='DELETE') or (did and action=='retry-extraction' and method=='POST') or (did and revision and ((confirmation and method=='POST') or (not confirmation and method=='GET')))
    if not valid:raise Problem(404,'not_found','요청한 경로를 찾을 수 없습니다.')
    if not owner:raise Problem(401,'unauthorized','세션이 만료되었거나 유효하지 않습니다.')
    row=repo.plan(rid,owner['owner_id'])
    if not row:raise Problem(404,'not_found','계획을 찾을 수 없습니다.')
    if not did and method=='GET':
        db.execute('BEGIN'); row=repo.plan(rid,owner['owner_id'])
        docs=[summary(d) for d in documents.list_active(rid)]
        db.commit();handler.respond(200,{'documents':docs,'input_revision':row['input_revision'],'analysis_eligible':any(d['analysis_eligible'] for d in docs),'upload_policy':{'max_files':MAX_DOCUMENTS,'max_file_bytes':MAX_DOCUMENT_BYTES,'extensions':['pdf','docx','txt']}});return True
    doc=documents.get(rid,did) if did else None
    if did and not doc:raise Problem(404,'not_found','문서를 찾을 수 없습니다.')
    if did and doc['removed_at']:raise Problem(410,'removed','삭제된 문서입니다.')
    if revision and not confirmation and method=='GET':
        item=documents.extraction(did,int(revision))
        if not item:raise Problem(404,'not_found','추출 버전을 찾을 수 없습니다.')
        handler.respond(200,{'document_id':did,'extraction_revision':item['extraction_revision'],'extracted_text':item['extracted_text'],'segments':json.loads(item['segments']),'limitations':json.loads(item['limitations']),'extraction_status':item['extraction_status'],'is_current_revision':doc['extraction_revision']==item['extraction_revision'],'partial_confirmed':bool(doc['partial_confirmed_at']) and doc['extraction_revision']==item['extraction_revision']});return True
    if not did:
        filename,data,mime,expected=request_file(handler,Problem)
        key=str(uuid.uuid4()); store=get_storage(); saved=False
        try:
            db.execute('BEGIN IMMEDIATE'); row=repo.plan(rid,owner['owner_id'])
            if expected!=row['input_revision']:raise Problem(409,'revision_conflict','입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')
            if documents.count_active(rid)>=MAX_DOCUMENTS:raise Problem(422,'file_limit','등록 가능한 문서 개수를 초과했습니다.')
            store.save(key,data);saved=True;t=timestamp()
            documents.create(key,rid,filename,mime,len(data),t)
            documents.bump_input(rid,t)
            result=summary(documents.get(rid,key));db.commit()
        except Exception:
            if saved:store.delete(key)
            raise
        handler.respond(201,{'document':result,'input_revision':row['input_revision']+1});return True
    body=handler.body(); db.execute('BEGIN IMMEDIATE');row=repo.plan(rid,owner['owner_id']);doc=documents.get(rid,did)
    if not doc or doc['removed_at']:raise Problem(410,'removed','삭제된 문서입니다.')
    check_revision(body,row,Problem);t=timestamp()
    if method=='DELETE':
        documents.remove(did,t)
        documents.bump_input(rid,t);db.commit()
        handler.respond(200,{'document_id':did,'cleanup_status':'queued','input_revision':row['input_revision']+1});return True
    if action=='retry-extraction':
        if doc['extraction_status']=='pending':raise Problem(409,'already_pending','이미 문서를 읽고 있습니다.')
        if doc['extraction_status']=='needs_ocr':raise Problem(422,'needs_ocr','OCR이 필요한 문서는 다시 등록해 주세요.')
        new_rev=doc['extraction_revision']+1
        documents.retry(did,new_rev,t)
        documents.bump_input(rid,t);db.commit()
        handler.respond(202,{'document_id':did,'extraction_revision':new_rev,'extraction_status':'pending','input_revision':row['input_revision']+1});return True
    if int(revision)!=doc['extraction_revision']:raise Problem(409,'revision_conflict','문서 추출 버전이 변경되었습니다.')
    if doc['extraction_status']!='partial':raise Problem(422,'not_partial','일부 추출 문서만 확인할 수 있습니다.')
    item=documents.extraction(did,int(revision))
    if not item or not item['extracted_text'] or not item['extracted_text'].strip():raise Problem(422,'empty_text','확인할 본문이 없습니다.')
    if not doc['partial_confirmed_at']:
        documents.confirm(did,t);documents.bump_input(rid,t);new_input=row['input_revision']+1
    else:t=doc['partial_confirmed_at'];new_input=row['input_revision']
    db.commit();handler.respond(200,{'partial_confirmed_at':t,'analysis_eligible':True,'input_revision':new_input});return True

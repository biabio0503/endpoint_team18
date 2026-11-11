"""Synthetic documents, real isolated DB reservations, mocked Google only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sqlite3
import os
import threading
import uuid
from unittest.mock import Mock
import pytest
from docx import Document
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject, DictionaryObject, DecodedStreamObject
from providers.document_parser import extract
from providers.document_images import pdf_page_image
from providers.google_vision_ocr import GoogleVisionOCR, OCRError, availability
from repositories.documents import DocumentRepository
from services import document_ocr as service
from services.document_ocr import DocumentOCR, LeaseLost
from worker import documents as worker

TEXT = '제가 Python 3.14와 FastAPI로 API 12개를 구현했습니다. 한국어 English C++ PostgreSQL 99.5%'


def png():
    out = BytesIO()
    with Image.new('RGB', (200, 80), 'white') as image:
        ImageDraw.Draw(image).text((10, 10), 'Python API 12', fill='black')
        image.save(out, 'PNG')
    return out.getvalue()


def pdf(kinds):
    writer = PdfWriter()
    for kind in kinds:
        page = writer.add_blank_page(200, 200)
        resources = DictionaryObject(); operations = b''
        if kind in ('text', 'logo'):
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            resources[NameObject('/Font')] = DictionaryObject({NameObject('/F1'):writer._add_object(font)})
            operations += b'BT /F1 12 Tf 10 180 Td (Native Python API 12) Tj ET\n'
        if kind in ('scan', 'logo', 'white'):
            image = DecodedStreamObject()
            with Image.open(BytesIO(png())) as im:
                image.set_data(bytes([255])*(200*80*3) if kind=='white' else im.tobytes())
            image.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(200),NameObject('/Height'):NumberObject(80),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'):writer._add_object(image)})
            operations += b'q 20 0 0 10 10 10 cm /Im1 Do Q' if kind=='logo' else b'q 200 0 0 200 0 0 cm /Im1 Do Q'
        stream = DecodedStreamObject(); stream.set_data(operations)
        page[NameObject('/Resources')] = resources
        page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO(); writer.write(out)
    return out.getvalue()


def docx(images=True, text=False):
    doc = Document()
    if text:
        doc.add_paragraph('원래 본문')
        doc.add_table(rows=1, cols=1).cell(0, 0).text='표의 텍스트'
    if images:
        doc.add_picture(BytesIO(png())); doc.add_picture(BytesIO(png()))
    out = BytesIO(); doc.save(out)
    return out.getvalue()


class ParserOCR:
    def __init__(self): self.calls=[]
    def __call__(self, key, image):
        content=image()
        if content is None: return {'text':'','blank':True}
        assert content.startswith(b'\x89PNG')
        self.calls.append(key)
        return {'text':TEXT,'segments':[{'start':0,'end':len(TEXT),'ocr_paragraph':1,'bbox':[[0,0],[100,40]]}]}


@pytest.mark.parametrize('kinds,count,status', [(['text'],0,'ready'),(['scan'],1,'ready'),
    (['text','scan','text'],1,'ready'),(['logo'],0,'ready'),(['blank'],0,'failed'),(['white'],0,'failed')])
def test_pdf_selection_order_offsets(kinds,count,status):
    ocr=ParserOCR(); result=extract('pdf',pdf(kinds),ocr=ocr)
    assert len(ocr.calls)==count and result['status']==status
    for segment in result['segments']:
        assert result['text'][segment['start']:segment['end']]
        assert segment['page'] in range(1,len(kinds)+1)
    if 'scan' in kinds:
        assert TEXT in result['text']
        assert next(s for s in result['segments'] if s.get('source'))['page']==kinds.index('scan')+1
    if kinds==['text','scan','text']:
        assert [s['page'] for s in result['segments'] if 'ocr_paragraph' not in s]==[1,2,3]


def test_pdf_individual_failure_preserves_other_pages():
    ocr=ParserOCR()
    def call(key,image):
        if key.endswith(':2'): raise OCRError('ocr_timeout')
        return ocr(key,image)
    result=extract('pdf',pdf(['text','scan','scan']),ocr=call)
    assert result['status']=='partial' and result['error_code']=='ocr_timeout'
    assert 'Native Python' in result['text'] and TEXT in result['text']
    assert [s['page'] for s in result['segments'] if 'ocr_paragraph' not in s]==[1,3]


def test_docx_referenced_images_deduplicated_and_native_text():
    ocr=ParserOCR(); result=extract('docx',docx(text=True),ocr=ocr)
    assert result['status']=='ready' and len(ocr.calls)==1
    assert result['text']=='원래 본문\n표의 텍스트\n'+TEXT
    assert next(s for s in result['segments'] if s.get('source'))['paragraph']==3
    assert 'page' not in result['segments'][-1]
    assert extract('docx',docx(),ocr=ParserOCR())['status']=='ready'
    assert extract('docx',docx())['status']=='needs_ocr'
    assert extract('docx',docx(text=True))['status']=='partial'


def test_docx_unused_media_and_txt_never_call_ocr():
    import zipfile
    content=BytesIO(docx(images=False,text=True))
    with zipfile.ZipFile(content,'a') as archive: archive.writestr('word/media/unreferenced.png',png())
    ocr=Mock(side_effect=AssertionError('must not call'))
    assert extract('docx',content.getvalue(),ocr=ocr)['status']=='ready'
    assert extract('txt',TEXT.encode(),ocr=ocr)['text']==TEXT
    assert extract('docx',docx(images=False,text=True),ocr=ocr)['status']=='ready'
    ocr.assert_not_called()


def test_render_bounds():
    with Image.open(BytesIO(pdf_page_image(pdf(['scan']),0))) as image: assert max(image.size)<=2000


@pytest.fixture
def ledger(tmp_path,monkeypatch):
    postgres=os.environ.get('ROADMAP_OCR_TEST_BACKEND')=='postgres'
    cleanup=lambda:None
    if postgres:
        import importlib.util
        import psycopg
        from repositories.postgres import connect_postgres
        safety=Path(__file__).resolve().parents[1]/'integration/postgres_test_safety.py'
        spec=importlib.util.spec_from_file_location('ocr_pg_safety',safety)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        url=module.validate_reset_target(os.environ.get('ROADMAP_TEST_POSTGRES_URL',''),os.environ)
        schema='ocr_test_'+uuid.uuid4().hex
        with psycopg.connect(url,autocommit=True) as admin:
            if admin.info.dbname!='team18_document_test' or admin.execute("SELECT to_regnamespace('supabase_migrations')").fetchone()[0] is not None:
                pytest.fail('Refusing a non-test database')
            admin.execute(f'CREATE SCHEMA "{schema}"')
            admin.execute(f'CREATE TABLE "{schema}".roadmap_inputs(request_id text PRIMARY KEY, input_revision integer NOT NULL DEFAULT 0, updated_at timestamptz)')
            admin.execute("DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF; IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF; END $$")
            root=Path(__file__).resolve().parents[4]
            for name in ('20261108122001_phase3_documents.sql','20261110091129_document_ocr_units.sql'):
                admin.execute((root/'supabase/migrations'/name).read_text().replace('public.',f'"{schema}".'))
            admin.execute(f"INSERT INTO \"{schema}\".roadmap_inputs(request_id) VALUES('plan')")
        def connect():
            db=connect_postgres(url); db.execute(f'SET search_path TO "{schema}"'); return db
        def cleanup():
            with psycopg.connect(url,autocommit=True) as admin: admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    else:
        path=tmp_path/'ocr.sqlite3'
        def connect():
            db=sqlite3.connect(path,isolation_level=None,timeout=10); db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON'); return db
        with closing(connect()) as db:
            for file in sorted((Path(__file__).resolve().parents[2]/'migrations').glob('*.sql')): db.executescript(file.read_text())
            db.execute("INSERT INTO session_owners(owner_id,token_digest,expires_at,created_at) VALUES('owner','digest','2099-01-01','2026-01-01')")
            db.execute("INSERT INTO roadmap_inputs(request_id,owner_id,created_at,updated_at) VALUES('plan','owner','2026-01-01','2026-01-01')")
    monkeypatch.setattr(service,'connect',connect); monkeypatch.setattr(worker,'connect',connect)
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT','900'); monkeypatch.setenv('ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT','50')
    try: yield connect
    finally: cleanup()


def new_job(connect,mime='application/pdf'):
    did=str(uuid.uuid4())
    with closing(connect()) as db:
        repo=DocumentRepository(db); repo.create(did,'plan','synthetic.pdf',mime,100,worker.timestamp())
        repo.lease(did,'token',worker.later(120),False)
        return dict(repo.get_any(did))


def reader(connect,provider=None):
    row=new_job(connect); provider=provider or Mock(detect=Mock(return_value={'text':TEXT,'segments':[]}))
    return DocumentOCR(row,'token',lambda:None,provider),provider


def test_persistent_cache_and_revision_reuse(ledger):
    ocr,provider=reader(ledger)
    assert ocr.read('page:1',png)['text']==TEXT and ocr.read('page:1',png)['text']==TEXT
    with closing(ledger()) as db:
        repo=DocumentRepository(db); repo.retry(ocr.row['document_id'],2,worker.timestamp())
        repo.lease(ocr.row['document_id'],'new-token',worker.later(120),False)
        row=dict(repo.get_any(ocr.row['document_id']))
    resumed=DocumentOCR(row,'new-token',lambda:None,provider)
    assert resumed.read('page:1',png)['text']==TEXT and provider.detect.call_count==1


@pytest.mark.parametrize('code',['ocr_auth_error','ocr_api_error','ocr_quota_exceeded','ocr_timeout'])
def test_failures_remain_charged_and_never_repeat(ledger,code):
    ocr,provider=reader(ledger,Mock(detect=Mock(side_effect=OCRError(code))))
    for _ in range(2):
        with pytest.raises(OCRError) as error: ocr.read('page:1',png)
        assert error.value.code==code
    assert provider.detect.call_count==1
    with closing(ledger()) as db: assert service.remaining(db)==899


def test_ambiguous_crash_is_not_repeated(ledger):
    ocr,provider=reader(ledger,Mock(detect=Mock(side_effect=SystemExit())))
    with pytest.raises(SystemExit): ocr.read('page:1',png)
    with pytest.raises(OCRError) as error: ocr.read('page:1',png)
    assert error.value.code=='ocr_uncertain' and provider.detect.call_count==1
    with closing(ledger()) as db: assert db.execute('SELECT status FROM document_ocr_units').fetchone()['status']=='reserved'


def test_atomic_month_budget_across_documents(ledger,monkeypatch):
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT','3')
    readers=[reader(ledger) for _ in range(12)]; barrier=threading.Barrier(len(readers))
    def run(item):
        barrier.wait()
        try: item[0].read('page:1',png); return 'ok'
        except OCRError as error: return error.code
    with ThreadPoolExecutor(max_workers=12) as pool: results=list(pool.map(run,readers))
    assert results.count('ok')==3 and results.count('ocr_budget_exceeded')==9
    assert sum(p.detect.call_count for _,p in readers)==3


def test_same_unit_concurrent_call(ledger):
    entered,release=threading.Event(),threading.Event()
    def detect(content): entered.set(); assert release.wait(5); return {'text':TEXT,'segments':[]}
    ocr,provider=reader(ledger,Mock(detect=Mock(side_effect=detect)))
    with ThreadPoolExecutor() as pool:
        future=pool.submit(ocr.read,'page:1',png); assert entered.wait(5)
        try:
            with pytest.raises(OCRError) as error: ocr.read('page:1',png)
            assert error.value.code=='ocr_uncertain'
        finally: release.set()
        assert future.result()['text']==TEXT
    assert provider.detect.call_count==1


def test_utc_month_and_hard_ceiling(ledger,monkeypatch):
    monkeypatch.setattr(service,'now',lambda:datetime(2026,11,30,23,59,tzinfo=timezone.utc))
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT','999999'); ocr,_=reader(ledger)
    with closing(ledger()) as db: db.execute("UPDATE project_documents SET extraction_lease_until='2099-01-01T00:00:00+00:00'")
    ocr.read('page:1',png)
    with closing(ledger()) as db:
        assert service.remaining(db)==899
        assert db.execute('SELECT usage_month FROM document_ocr_units').fetchone()['usage_month']=='2026-11'
        monkeypatch.setattr(service,'now',lambda:datetime(2026,12,1,0,0,tzinfo=timezone.utc))
        assert service.remaining(db)==900
    ocr.read('page:1',png)


@pytest.mark.parametrize('change',["removed_at='2026-11-10'",'extraction_revision=2',"extraction_lease_token='other'","extraction_lease_until='2000-01-01T00:00:00+00:00'"])
def test_invalid_job_never_dispatches(ledger,change):
    ocr,provider=reader(ledger)
    with closing(ledger()) as db: db.execute('UPDATE project_documents SET '+change)
    with pytest.raises(LeaseLost): ocr.read('page:1',png)
    provider.detect.assert_not_called()


def test_deletion_during_rpc_does_not_restore_text_or_refund(ledger):
    ocr,provider=reader(ledger)
    def detect(content):
        with closing(ledger()) as db: DocumentRepository(db).remove(ocr.row['document_id'],worker.timestamp())
        return {'text':TEXT,'segments':[]}
    provider.detect.side_effect=detect; ocr.read('page:1',png)
    with closing(ledger()) as db:
        saved=db.execute('SELECT * FROM document_ocr_units').fetchone()
        assert saved['result_json'] is None and service.remaining(db)==899


def test_lease_renewal_and_lost_token(ledger):
    row=new_job(ledger)
    with closing(ledger()) as db: db.execute('UPDATE project_documents SET extraction_lease_until=?',(worker.later(1),))
    lease=worker.ExtractionLease(row,'token'); lease.check()
    with closing(ledger()) as db:
        until=db.execute('SELECT extraction_lease_until FROM project_documents').fetchone()['extraction_lease_until']
        assert ((datetime.fromisoformat(until) if isinstance(until,str) else until)-datetime.now(timezone.utc)).total_seconds()>110
        db.execute("UPDATE project_documents SET extraction_lease_token='other'")
    with pytest.raises(LeaseLost): lease.check(force=True)


def test_worker_partial_limit_and_project_evidence(ledger,monkeypatch):
    from services.project_experience import documents_for_analysis
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT','1'); row=new_job(ledger)
    with closing(ledger()) as db: db.execute('UPDATE project_documents SET extraction_lease_until=NULL,extraction_lease_token=NULL')
    provider=Mock(detect=Mock(return_value={'text':TEXT,'segments':[]}))
    assert worker.run_once(Mock(read=Mock(return_value=pdf(['text','scan','scan']))),ocr_provider=provider)
    with closing(ledger()) as db:
        repo=DocumentRepository(db); result=repo.extraction(row['document_id'],1)
        assert result['extraction_status']=='partial' and result['error_code']=='ocr_budget_exceeded'
        assert TEXT in result['extracted_text'] and 'Native Python' in result['extracted_text']
        eligible,excluded,_=documents_for_analysis(db,'plan'); assert not eligible and excluded[0]['reason']=='partial_unconfirmed'
        repo.confirm(row['document_id'],worker.timestamp())
        eligible,_,_=documents_for_analysis(db,'plan'); assert eligible[0]['extracted_text']==result['extracted_text']
        repo.retry(row['document_id'],2,worker.timestamp())
        eligible,_,_=documents_for_analysis(db,'plan'); assert not eligible
    assert provider.detect.call_count==1


def test_credentials_absent_no_network_or_reservation(tmp_path,monkeypatch,ledger):
    monkeypatch.setenv('ROADMAP_OCR_PROVIDER','google_vision'); monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS',str(tmp_path/'missing.json'))
    assert availability()=='ocr_credentials_missing'
    ocr=DocumentOCR(new_job(ledger),'token',lambda:None)
    with pytest.raises(OCRError) as error: ocr.read('page:1',Mock(side_effect=AssertionError()))
    assert error.value.code=='ocr_credentials_missing'
    with closing(ledger()) as db: assert service.remaining(db)==900


def test_sdk_exact_text_timeout_no_retry_and_error_codes():
    from google.cloud import vision
    from google.api_core import exceptions
    client=Mock(); client.document_text_detection.return_value=vision.AnnotateImageResponse(full_text_annotation=vision.TextAnnotation(text=TEXT))
    provider=GoogleVisionOCR(client); assert provider.detect(png())['text']==TEXT
    arguments=client.document_text_detection.call_args.kwargs
    assert arguments['retry'] is None and arguments['timeout']==25
    assert list(arguments['image_context'].language_hints)==['ko','en']
    for exception,code in [(exceptions.Unauthenticated,'ocr_auth_error'),(exceptions.PermissionDenied,'ocr_auth_error'),(exceptions.ResourceExhausted,'ocr_quota_exceeded'),(exceptions.DeadlineExceeded,'ocr_timeout'),(exceptions.ServiceUnavailable,'ocr_api_error')]:
        client.document_text_detection.side_effect=exception('sensitive detail')
        with pytest.raises(OCRError) as error: provider.detect(png())
        assert error.value.code==code and 'sensitive' not in str(error.value)
    client.document_text_detection.side_effect=None
    for status,code in [(8,'ocr_quota_exceeded'),(16,'ocr_auth_error'),(4,'ocr_timeout'),(13,'ocr_api_error')]:
        client.document_text_detection.return_value=vision.AnnotateImageResponse(error={'code':status,'message':'sensitive'})
        with pytest.raises(OCRError) as error: provider.detect(png())
        assert error.value.code==code


def test_long_running_ocr_renews_lease_and_cannot_be_reclaimed(ledger,monkeypatch):
    import time
    monkeypatch.setattr(worker,'LEASE_SECONDS',1)
    row=new_job(ledger)
    with closing(ledger()) as db: db.execute('UPDATE project_documents SET extraction_lease_until=NULL,extraction_lease_token=NULL')
    entered,release=threading.Event(),threading.Event()
    def detect(content): entered.set(); assert release.wait(5); return {'text':TEXT,'segments':[]}
    provider=Mock(detect=Mock(side_effect=detect))
    with ThreadPoolExecutor() as pool:
        future=pool.submit(worker.run_once,Mock(read=Mock(return_value=pdf(['scan']))),provider)
        assert entered.wait(5)
        try:
            time.sleep(1.5)  # Exceeds the scaled lease; heartbeat is real, not mocked.
            assert worker.claim() is None
        finally: release.set()
        assert future.result()
    with closing(ledger()) as db: assert DocumentRepository(db).get_any(row['document_id'])['extraction_status']=='ready'


def test_document_limit_and_disabled_provider_do_not_reserve(ledger,monkeypatch):
    monkeypatch.setenv('ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT','1')
    ocr,provider=reader(ledger)
    ocr.read('page:1',png)
    with pytest.raises(OCRError) as error: ocr.read('page:2',png)
    assert error.value.code=='ocr_document_limit'
    assert provider.detect.call_count==1
    disabled=DocumentOCR(new_job(ledger),'token',lambda:None)
    with pytest.raises(OCRError) as error: disabled.read('page:1',png)
    assert error.value.code=='ocr_disabled'
    with closing(ledger()) as db: assert service.remaining(db)==899


def test_post_call_revision_change_cannot_finish_old_extraction(ledger):
    row=new_job(ledger)
    with closing(ledger()) as db: db.execute('UPDATE project_documents SET extraction_lease_until=NULL,extraction_lease_token=NULL')
    def detect(content):
        with closing(ledger()) as db: DocumentRepository(db).retry(row['document_id'],2,worker.timestamp())
        return {'text':TEXT,'segments':[]}
    provider=Mock(detect=Mock(side_effect=detect))
    assert worker.run_once(Mock(read=Mock(return_value=pdf(['scan']))),provider)
    with closing(ledger()) as db:
        repo=DocumentRepository(db)
        assert repo.extraction(row['document_id'],1)['extraction_status']=='pending'
        assert repo.get_any(row['document_id'])['extraction_revision']==2
    assert worker.run_once(Mock(read=Mock(return_value=pdf(['scan']))),provider)
    assert provider.detect.call_count==1


def test_db_unavailable_fails_closed_and_preserves_native_text(ledger,monkeypatch):
    ocr,provider=reader(ledger)
    monkeypatch.setattr(service,'connect',Mock(side_effect=OSError('secret DB detail')))
    result=extract('pdf',pdf(['text','scan']),ocr=ocr.read)
    assert result['status']=='partial' and result['error_code']=='ocr_storage_error'
    assert 'Native Python' in result['text']
    assert 'secret' not in str(result)
    provider.detect.assert_not_called()


@pytest.mark.skipif(os.environ.get('ROADMAP_OCR_TEST_BACKEND')!='postgres',reason='isolated PostgreSQL process test')
def test_postgres_budget_shared_across_processes(ledger,monkeypatch):
    import subprocess
    import sys
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT','3')
    rows=[new_job(ledger) for _ in range(8)]
    with closing(ledger()) as db: schema=db.execute('SELECT current_schema() AS name').fetchone()['name']
    script='''
import os, sys
from contextlib import closing
from unittest.mock import Mock
from repositories.postgres import connect_postgres
from services import document_ocr as service
def connect():
    db=connect_postgres(os.environ['ROADMAP_TEST_POSTGRES_URL'])
    db.execute('SET search_path TO "'+sys.argv[1]+'"')
    return db
service.connect=connect
with closing(connect()) as db:
    row=dict(db.execute('SELECT * FROM project_documents WHERE document_id=?',(sys.argv[2],)).fetchone())
ocr=service.DocumentOCR(row,'token',lambda:None,Mock(detect=Mock(return_value={'text':'synthetic','segments':[]})))
try:
    ocr.read('page:1',lambda:b'synthetic')
    print('ok')
except service.OCRError as error:
    print(error.code)
'''
    def run(row):
        process=subprocess.run([sys.executable,'-c',script,schema,row['document_id']],env=os.environ.copy(),capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stderr
        return process.stdout.strip()
    with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(run,rows))
    assert results.count('ok')==3 and results.count('ocr_budget_exceeded')==5
    with closing(ledger()) as db: assert service.remaining(db)==0


def test_transparent_docx_image_preserves_contrast():
    from providers.document_images import docx_image
    output=BytesIO()
    with Image.new('RGBA',(100,60),(0,0,0,0)) as image:
        ImageDraw.Draw(image).rectangle((10,10,30,30),fill=(0,0,0,255))
        image.save(output,'PNG')
    with Image.open(BytesIO(docx_image(output.getvalue()))) as converted:
        assert converted.getpixel((0,0))==(255,255,255)
        assert converted.getpixel((20,20))==(0,0,0)


def test_invalid_credentials_never_create_sdk_client(tmp_path,monkeypatch):
    from google.cloud import vision
    path=tmp_path/'invalid.json'; path.write_text('{"type":"service_account"}')
    monkeypatch.setenv('ROADMAP_OCR_PROVIDER','google_vision')
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS',str(path))
    client=Mock(side_effect=AssertionError('must not create client'))
    monkeypatch.setattr(vision,'ImageAnnotatorClient',client)
    assert availability()=='ocr_credentials_invalid'
    with pytest.raises(OCRError) as error: GoogleVisionOCR().detect(png())
    assert error.value.code=='ocr_credentials_invalid'
    client.assert_not_called()


def test_sdk_paragraph_coordinates_follow_verbatim_text():
    from google.cloud import vision
    text='한국어 English 12\nPython C++'
    paragraphs=[]
    for line in text.splitlines():
        paragraphs.append({'words':[{'symbols':[{'text':char} for char in word]} for word in line.split()],
                           'bounding_box':{'vertices':[{'x':1,'y':2},{'x':50,'y':20}]}})
    client=Mock()
    client.document_text_detection.return_value=vision.AnnotateImageResponse(full_text_annotation={
        'text':text,'pages':[{'blocks':[{'paragraphs':paragraphs}]}]})
    result=GoogleVisionOCR(client).detect(png())
    assert result['text']==text
    assert [text[s['start']:s['end']] for s in result['segments']]==text.splitlines()
    assert result['segments'][1]['ocr_paragraph']==2
    assert result['segments'][0]['bbox']==[[1,2],[50,20]]


def test_reduced_document_limit_can_be_raised_without_reupload(ledger,monkeypatch):
    row=new_job(ledger)
    row.update(extraction_status='needs_ocr',extraction_error_code='ocr_document_limit')
    policy={'available':True,'reason':None}
    with closing(ledger()) as db:
        monkeypatch.setenv('ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT','0')
        assert service.retry_policy(row,policy,db)['retry_available'] is False
        monkeypatch.setenv('ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT','1')
        assert service.retry_policy(row,policy,db)['retry_available'] is True

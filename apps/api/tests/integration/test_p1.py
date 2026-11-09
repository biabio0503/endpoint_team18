import concurrent.futures
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import sys
import unittest

TEMP = tempfile.TemporaryDirectory()
os.environ['ROADMAP_DB_BACKEND'] = 'sqlite'
os.environ['ROADMAP_DB_PATH'] = str(Path(TEMP.name) / 'test.sqlite3')
os.environ['ROADMAP_INSECURE_LOCAL_COOKIE'] = '1'
os.environ['ROADMAP_FILE_STORAGE_PATH'] = str(Path(TEMP.name) / 'files')
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
spec = importlib.util.spec_from_file_location('roadmap_api', Path(__file__).resolve().parents[2] / 'app' / 'main.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.migrate()
        from uvicorn_test_server import TestServer
        cls.server = TestServer(api.app)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        TEMP.cleanup()

    def request(self, method, path, data=None, cookie=None, origin='http://localhost:3000'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Origin': origin}
        if cookie: headers['Cookie'] = cookie
        if data is not None: headers['Content-Type'] = 'application/json'
        conn.request(method, '/api' + path, body=json.dumps(data) if data is not None else None, headers=headers)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        result = (resp.status, body, resp.getheader('Set-Cookie'))
        conn.close()
        return result

    def create(self):
        status, body, cookie = self.request('POST', '/roadmap-inputs')
        self.assertEqual(status, 201)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        return body['request_id'], cookie.split(';')[0]

    def patch(self, rid, cookie, revision, changes):
        return self.request('PATCH', '/roadmap-inputs/' + rid, {'expected_input_revision': revision, 'changes': changes}, cookie)

    def test_session_persistence_conflict_and_validation(self):
        rid, cookie = self.create()
        other_id, other_cookie = self.create()
        self.assertEqual(self.request('GET', '/roadmap-inputs/' + rid, cookie=other_cookie)[0], 404)
        self.assertEqual(self.patch(rid, other_cookie, 0, {'career_goal':'x'})[0], 404)
        self.assertEqual(self.request('GET', '/roadmap-inputs/' + rid)[0], 401)
        self.assertEqual(self.request('POST', '/roadmap-inputs', origin='http://evil.test')[0], 403)
        self.assertEqual(self.request('GET', '/roadmap-inputs/resume', cookie=cookie)[1]['request']['request_id'], rid)
        self.assertEqual(self.request('GET', '/roadmap-inputs/resume')[1], {'found': False, 'request': None})
        for changes in ({'career_goal':'  '}, {'career_goal':'x','gpa':0}, {'career_goal':'x','gpa':4.4,'gpa_scale':4.3}, {'career_goal':'x','earned_credits':-1}, {'career_goal':'x','year_level':5}, {'career_goal':'x','university_id':'unknown'}):
            self.assertEqual(self.patch(rid, cookie, 0, changes)[0], 422, changes)
        status, result, _ = self.patch(rid, cookie, 0, {'career_goal':'개발', 'earned_credits':0, 'gpa':0, 'gpa_scale':4.5})
        self.assertEqual(status, 200)
        self.assertEqual(result['input_revision'], 1)
        self.assertEqual(result['input']['earned_credits'], 0)
        self.assertEqual(result['input']['gpa'], 0)
        self.assertIsNone(result['input']['year_level'])
        self.assertEqual(self.patch(rid, cookie, 0, {'career_goal':'충돌'})[0], 409)
        self.assertEqual(self.patch(rid, cookie, 1, {'career_goal':'개발'})[1]['input_revision'], 1)
        api.migrate()  # reopening the same DB does not wipe existing data
        self.assertEqual(self.request('GET', '/roadmap-inputs/' + rid, cookie=cookie)[1]['input']['career_goal'], '개발')
        self.assertNotEqual(rid, other_id)

    def test_secure_cookie_and_expiration(self):
        from api import dependencies
        previous = dependencies.SECURE_COOKIE
        try:
            dependencies.SECURE_COOKIE = True
            status, body, cookie = self.request('POST', '/roadmap-inputs')
            self.assertEqual(status, 201)
            self.assertIn('; Secure', cookie)
        finally:
            dependencies.SECURE_COOKIE = previous
        token_cookie = cookie.split(';')[0]
        with api.closing(api.connect()) as db:
            db.execute("UPDATE session_owners SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_digest=?", (__import__('hashlib').sha256(token_cookie.split('=', 1)[1].encode()).hexdigest(),))
        self.assertEqual(self.request('GET', '/roadmap-inputs/' + body['request_id'], cookie=token_cookie)[0], 401)
        self.assertFalse(self.request('GET', '/roadmap-inputs/resume', cookie=token_cookie)[1]['found'])

    def test_relations_and_atomic_versions(self):
        with api.closing(api.connect()) as db:
            db.execute("INSERT INTO universities VALUES('u1','학교1',1),('u2','학교2',1)")
            db.execute("INSERT INTO departments VALUES('d1','u1','학과1',1),('d2','u2','학과2',1)")
            db.execute("INSERT INTO course_catalogs VALUES('c1','d1',NULL,'버전','범위','unknown','출처',NULL,'2026-01-01',NULL,1)")
        rid, cookie = self.create()
        self.assertEqual(self.patch(rid,cookie,0,{'career_goal':'목표','university_id':'u1','department_id':'d2'})[0],422)
        self.assertEqual(self.patch(rid,cookie,0,{'career_goal':'목표','university_id':'u2','department_id':'d2','catalog_id':'c1'})[0],422)
        result=self.patch(rid,cookie,0,{'career_goal':'목표','university_id':'u1','department_id':'d1','catalog_id':'c1'})[1]
        self.assertEqual((result['input_revision'],result['selection_revision'],result['review_status']),(1,1,'unconfirmed'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda goal:self.patch(rid,cookie,1,{'career_goal':goal})[0], ['목표1','목표2']))
        self.assertEqual(sorted(results),[200,409])
        result=self.request('GET','/roadmap-inputs/'+rid,cookie=cookie)[1]
        self.assertEqual(result['selection_revision'],1)

    def upload_document(self, rid, cookie, filename, data, revision):
        boundary='roadmap-test-boundary'
        parts=(b'--'+boundary.encode()+b'\r\nContent-Disposition: form-data; name="expected_input_revision"\r\n\r\n'+str(revision).encode()+b'\r\n--'+boundary.encode()+b'\r\nContent-Disposition: form-data; name="file"; filename="'+filename.encode()+b'"\r\nContent-Type: application/octet-stream\r\n\r\n'+data+b'\r\n--'+boundary.encode()+b'--\r\n')
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        conn.request('POST','/api/roadmap-inputs/'+rid+'/documents',body=parts,headers={'Origin':'http://localhost:3000','Cookie':cookie,'Content-Type':'multipart/form-data; boundary='+boundary})
        response=conn.getresponse(); result=(response.status,json.loads(response.read()));conn.close();return result

    def test_p3_scan_and_empty_text_status(self):
        from io import BytesIO
        from pypdf import PdfWriter
        from pypdf.generic import NameObject,DecodedStreamObject,DictionaryObject,NumberObject
        from worker.documents import run_once
        rid,cookie=self.create();base='/roadmap-inputs/'+rid+'/documents'
        pdf=PdfWriter();page=pdf.add_blank_page(100,100)
        image=DecodedStreamObject();image.set_data(bytes([255,0,0]));image.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(1),NameObject('/Height'):NumberObject(1),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Im1'):pdf._add_object(image)})})
        stream=DecodedStreamObject();stream.set_data(b'q 100 0 0 100 0 0 cm /Im1 Do Q');page[NameObject('/Contents')]=pdf._add_object(stream)
        output=BytesIO();pdf.write(output)
        status,scan=self.upload_document(rid,cookie,'scan.pdf',output.getvalue(),0);self.assertEqual(status,201);self.assertTrue(run_once())
        listing=self.request('GET',base,cookie=cookie)[1];self.assertEqual(listing['documents'][0]['extraction_status'],'needs_ocr')
        self.assertEqual(self.request('POST',base+'/'+scan['document']['document_id']+'/retry-extraction',{'expected_input_revision':listing['input_revision']},cookie)[0],422)
        status,empty=self.upload_document(rid,cookie,'empty.txt',b'   \n',listing['input_revision']);self.assertEqual(status,201);self.assertTrue(run_once())
        listing=self.request('GET',base,cookie=cookie)[1];self.assertEqual(next(d for d in listing['documents'] if d['document_id']==empty['document']['document_id'])['extraction_status'],'failed')
        self.assertFalse(listing['analysis_eligible'])
        retry=self.request('POST',base+'/'+empty['document']['document_id']+'/retry-extraction',{'expected_input_revision':listing['input_revision']},cookie)
        self.assertEqual((retry[0],retry[1]['extraction_revision']),(202,2));self.assertTrue(run_once())
        latest=self.request('GET',base,cookie=cookie)[1]
        self.assertEqual(next(d for d in latest['documents'] if d['document_id']==empty['document']['document_id'])['extraction_status'],'failed')
        previous=self.request('GET',base+'/'+empty['document']['document_id']+'/extractions/1',cookie=cookie)
        self.assertEqual(previous[1]['extraction_status'],'failed')

    def test_p3_limits_and_lease_claim(self):
        from api.routes import documents as routes
        from worker.documents import run_once, claim
        rid,cookie=self.create();base='/roadmap-inputs/'+rid+'/documents'
        old_count,old_bytes=routes.MAX_DOCUMENTS,routes.MAX_DOCUMENT_BYTES
        try:
            routes.MAX_DOCUMENT_BYTES=20;routes.MAX_DOCUMENTS=1
            self.assertEqual(self.upload_document(rid,cookie,'large.txt',b'x'*21,0)[0],413)
            self.assertEqual(self.upload_document(rid,cookie,'fake.txt',b'%PDF-1.4',0)[0],422)
            status,doc=self.upload_document(rid,cookie,'ok.txt',b'valid text',0);self.assertEqual(status,201)
            self.assertEqual(self.upload_document(rid,cookie,'second.txt',b'text',0)[0],409)
            self.assertEqual(self.upload_document(rid,cookie,'second.txt',b'text',1)[0],422)
            job=claim();self.assertIsNotNone(job)
            self.assertFalse(run_once())  # a live lease cannot be claimed again
            with api.closing(api.connect()) as db: db.execute("UPDATE project_documents SET extraction_lease_until='2000-01-01' WHERE document_id=?",(doc['document']['document_id'],))
            self.assertTrue(run_once())
            self.assertFalse(run_once())
            self.assertEqual(self.request('GET',base,cookie=cookie)[1]['documents'][0]['extraction_status'],'ready')
        finally: routes.MAX_DOCUMENTS=old_count;routes.MAX_DOCUMENT_BYTES=old_bytes

    def test_p3_text_retry_ownership_and_cleanup(self):
        from worker.documents import run_once
        from providers.document_storage import LocalDocumentStorage
        rid,cookie=self.create();_,other=self.create();base='/roadmap-inputs/'+rid+'/documents'
        status,result=self.upload_document(rid,cookie,'project.txt','실제 텍스트\n둘째 줄'.encode(),0)
        self.assertEqual(status,201);did=result['document']['document_id']
        self.assertEqual(self.upload_document(rid,cookie,'bad.txt',b'%PDF-1.4\x00',1)[0],422)
        self.assertEqual(self.request('GET',base,cookie=other)[0],404)
        self.assertFalse(self.request('GET',base,cookie=cookie)[1]['analysis_eligible'])
        self.assertTrue(run_once())
        listing=self.request('GET',base,cookie=cookie)[1];self.assertTrue(listing['analysis_eligible']);self.assertEqual(listing['documents'][0]['extraction_status'],'ready')
        version=base+'/'+did+'/extractions/1'
        result=self.request('GET',version,cookie=cookie)[1]
        self.assertEqual(result['extracted_text'],'실제 텍스트\n둘째 줄');self.assertEqual(result['segments'][0]['start'],0)
        self.assertEqual(self.request('GET',version,cookie=other)[0],404)
        self.assertEqual(self.request('POST',base+'/'+did+'/retry-extraction',{'expected_input_revision':0},cookie)[0],409)
        retry=self.request('POST',base+'/'+did+'/retry-extraction',{'expected_input_revision':listing['input_revision']},cookie)
        self.assertEqual((retry[0],retry[1]['extraction_revision']),(202,2))
        self.assertEqual(self.request('POST',base+'/'+did+'/retry-extraction',{'expected_input_revision':retry[1]['input_revision']},cookie)[0],409)
        self.assertTrue(run_once()); listing=self.request('GET',base,cookie=cookie)[1]
        self.assertEqual(self.request('GET',version,cookie=cookie)[1]['extracted_text'],'실제 텍스트\n둘째 줄')
        self.assertEqual(self.request('DELETE',base+'/'+did,{'expected_input_revision':listing['input_revision']},other)[0],404)
        deleted=self.request('DELETE',base+'/'+did,{'expected_input_revision':listing['input_revision']},cookie)
        self.assertEqual(deleted[0],200);self.assertFalse(self.request('GET',base,cookie=cookie)[1]['analysis_eligible'])
        self.assertEqual(self.request('GET',version,cookie=cookie)[0],410)
        class BrokenStorage:
            def delete(self,key): raise OSError('injected')
        self.assertTrue(run_once(BrokenStorage()))
        with api.closing(api.connect()) as db:
            row=db.execute('SELECT cleanup_status,storage_key FROM project_documents WHERE document_id=?',(did,)).fetchone();self.assertEqual(row['cleanup_status'],'failed')
            self.assertTrue(LocalDocumentStorage().path(row['storage_key']).exists())
            db.execute('UPDATE project_documents SET cleanup_lease_until=NULL WHERE document_id=?',(did,))
        self.assertTrue(run_once())
        with api.closing(api.connect()) as db:
            self.assertEqual(db.execute('SELECT cleanup_status FROM project_documents WHERE document_id=?',(did,)).fetchone()[0],'succeeded')
            self.assertEqual(db.execute('SELECT count(*) FROM document_extractions WHERE document_id=?',(did,)).fetchone()[0],0)
        self.assertFalse(LocalDocumentStorage().path(did).exists())

    def test_p3_formats_partial_review_and_recovery(self):
        from io import BytesIO
        from docx import Document
        from pypdf import PdfWriter
        from pypdf.generic import NameObject,DecodedStreamObject,DictionaryObject
        from worker.documents import run_once
        rid,cookie=self.create();base='/roadmap-inputs/'+rid+'/documents'
        # A real DOCX with body text plus embedded image must be partial.
        import base64
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lK0AAAAASUVORK5CYII=')
        doc=Document();doc.add_paragraph('실제 본문');doc.add_picture(BytesIO(png));buf=BytesIO();doc.save(buf)
        status,result=self.upload_document(rid,cookie,'sample.docx',buf.getvalue(),0);self.assertEqual(status,201);did=result['document']['document_id']
        with api.closing(api.connect()) as db: db.execute("UPDATE project_documents SET extraction_lease_until='2000-01-01',extraction_lease_token='interrupted' WHERE document_id=?",(did,))
        self.assertTrue(run_once());lst=self.request('GET',base,cookie=cookie)[1];self.assertEqual(lst['documents'][0]['extraction_status'],'partial');self.assertFalse(lst['analysis_eligible'])
        endpoint=base+'/'+did+'/extractions/1';ex=self.request('GET',endpoint,cookie=cookie)[1];self.assertIn('실제 본문',ex['extracted_text']);self.assertTrue(ex['limitations'])
        self.assertEqual(self.request('POST',endpoint+'/confirmation',{'expected_input_revision':0},cookie)[0],409)
        response=self.request('POST',endpoint+'/confirmation',{'expected_input_revision':lst['input_revision']},cookie);self.assertTrue(response[1]['analysis_eligible'])
        self.assertTrue(self.request('GET',base,cookie=cookie)[1]['analysis_eligible'])
        # Proper PDF with text, followed by an empty page; missing text must not be ready.
        pdf=PdfWriter();page=pdf.add_blank_page(width=100,height=100)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):pdf._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 50 Td (Hello PDF) Tj ET');page[NameObject('/Contents')]=pdf._add_object(stream)
        pdf.add_blank_page(width=100,height=100);out=BytesIO();pdf.write(out)
        revision=response[1]['input_revision'];status,pdfdoc=self.upload_document(rid,cookie,'sample.pdf',out.getvalue(),revision);self.assertEqual(status,201)
        self.assertTrue(run_once());lst=self.request('GET',base,cookie=cookie)[1];pd=next(d for d in lst['documents'] if d['document_id']==pdfdoc['document']['document_id']);self.assertEqual(pd['extraction_status'],'partial')
        detail=self.request('GET',base+'/'+pd['document_id']+'/extractions/1',cookie=cookie)[1];self.assertIn('Hello PDF',detail['extracted_text']);self.assertEqual(detail['segments'][0]['page'],1)
        # A blank page without an image is a read failure, not an OCR claim.
        pdf=PdfWriter();pdf.add_blank_page(width=100,height=100);out=BytesIO();pdf.write(out)
        status,blank=self.upload_document(rid,cookie,'blank.pdf',out.getvalue(),lst['input_revision']);self.assertEqual(status,201);self.assertTrue(run_once())
        lst=self.request('GET',base,cookie=cookie)[1];self.assertEqual(next(d for d in lst['documents'] if d['document_id']==blank['document']['document_id'])['extraction_status'],'failed')
        self.assertEqual(self.upload_document(rid,cookie,'bad.docx',b'not a zip',lst['input_revision'])[0],422)
        self.assertEqual(self.upload_document(rid,cookie,'bad.pdf',b'%PDF-not-valid',lst['input_revision'])[0],422)

    def test_p5_cross_session_writes_and_no_ai_runs(self):
        from worker.documents import run_once
        seed_spec=importlib.util.spec_from_file_location('seed_p5', Path(__file__).resolve().parents[2] / 'app' / 'scripts' / 'seed_dev.py')
        seed=importlib.util.module_from_spec(seed_spec);seed_spec.loader.exec_module(seed);seed.seed()
        rid,cookie=self.create();_,other=self.create();base='/roadmap-inputs/'+rid
        self.assertEqual(self.patch(rid,cookie,0,{'career_goal':'진로','university_id':seed.U,'department_id':seed.D,'catalog_id':seed.C1})[0],200)
        status,doc=self.upload_document(rid,cookie,'document.txt',b'project input',1);self.assertEqual(status,201)
        did=doc['document']['document_id'];self.assertTrue(run_once())
        before=self.request('GET',base,cookie=cookie)[1]
        self.assertEqual(self.upload_document(rid,other,'attack.txt',b'other session',before['input_revision'])[0],404)
        changes={'catalog_id':seed.C1,'expected_selection_revision':1,'changes':[{'course_id':seed.rows[0][0],'is_completed':True}]}
        self.assertEqual(self.request('PATCH',base+'/course-selections',changes,other)[0],404)
        review={'catalog_id':seed.C1,'expected_selection_revision':1,'expected_input_revision':before['input_revision'],'reported_missing_courses':False}
        self.assertEqual(self.request('POST',base+'/course-selection-review',review,other)[0],404)
        self.assertEqual(self.request('POST',base+'/documents/'+did+'/retry-extraction',{'expected_input_revision':before['input_revision']},other)[0],404)
        self.assertEqual(self.request('GET',base+'/documents/'+did+'/extractions/1',cookie=other)[0],404)
        self.assertEqual(self.request('POST',base+'/runs',{},cookie)[0],404)
        self.assertEqual(self.request('POST',base+'/analysis-jobs',{},cookie)[0],404)
        self.assertEqual(self.request('GET',base,cookie=cookie)[1],before)
        with api.closing(api.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('analysis_jobs','analysis_items')").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM roadmap_runs WHERE request_id=?', (rid,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM input_course_states WHERE request_id=?',(rid,)).fetchone()[0],0)

    def test_p2_course_lifecycle(self):
        seed_spec=importlib.util.spec_from_file_location('seed_dev', Path(__file__).resolve().parents[2] / 'app' / 'scripts' / 'seed_dev.py')
        seed=importlib.util.module_from_spec(seed_spec); seed_spec.loader.exec_module(seed); seed.seed(); seed.seed()
        self.assertTrue(any(x['university_id']==seed.U for x in self.request('GET','/universities')[1]['universities']))
        self.assertEqual(self.request('GET','/universities/'+seed.U+'/departments')[1]['departments'][0]['department_id'],seed.D)
        self.assertEqual(len(self.request('GET','/departments/'+seed.D+'/catalogs')[1]['catalogs']),2)
        self.assertEqual(self.request('GET','/departments/nonexistent/catalogs')[0],404)
        rid,cookie=self.create(); _,other=self.create()
        base='/roadmap-inputs/'+rid
        r=self.patch(rid,cookie,0,{'career_goal':'진로','university_id':seed.U,'department_id':seed.D,'catalog_id':seed.C1})
        self.assertEqual(r[0],200)
        def listing(query=''):
            return self.request('GET',base+'/courses?catalog_id='+seed.C1+query,cookie=cookie)
        self.assertEqual(self.request('GET',base+'/courses?catalog_id='+seed.C1,cookie=other)[0],404)
        result=listing()[1]
        self.assertEqual(result['review_status'],'unconfirmed'); self.assertEqual(result['selection_summary']['count'],0)
        self.assertIsNone(result['courses'][0]['theory_hours']); self.assertIsNone(result['courses'][0]['practice_hours'])
        review=lambda selection,inputrev,missing: self.request('POST',base+'/course-selection-review',{'catalog_id':seed.C1,'expected_selection_revision':selection,'expected_input_revision':inputrev,'reported_missing_courses':missing},cookie)
        self.assertEqual(review(0,1,False)[0],409)
        confirmed=review(1,1,False)
        self.assertEqual(confirmed[1]['review_status'],'confirmed')
        self.assertEqual(listing()[1]['courses'][0]['completion_state'],'not_selected_in_reviewed_catalog')
        self.assertEqual(review(1,1,True)[0],409)
        partial=review(1,2,True)
        self.assertEqual(partial[1]['review_status'],'partial')
        changes=lambda rev, items:self.request('PATCH',base+'/course-selections',{'catalog_id':seed.C1,'expected_selection_revision':rev,'changes':items},cookie)
        selected=seed.rows[3][0]
        self.assertEqual(changes(1,[{'course_id':selected,'is_completed':'true'}])[0],422)
        self.assertEqual(changes(1,[{'course_id':selected,'is_completed':True}]*2)[0],422)
        result=changes(1,[{'course_id':selected,'is_completed':True}])
        self.assertEqual((result[1]['selection_revision'],result[1]['input_revision'],result[1]['review_status']),(2,4,'unconfirmed'))
        self.assertEqual(changes(1,[{'course_id':selected,'is_completed':False}])[0],409)
        self.assertEqual(changes(2,[{'course_id':selected,'is_completed':True}])[1]['selection_revision'],2)
        result=listing('&completed_only=true&page_size=1')[1]
        self.assertEqual(result['selection_summary'],{'count':1,'known_credits':0.0,'unknown_credits_count':1})
        self.assertEqual(len(result['courses']),1)
        self.assertEqual(listing('&q=DEV301')[1]['courses'][0]['course_id'],selected)
        self.assertEqual(listing('&year=3&category=%EC%A0%84%EA%B3%B5%ED%95%84%EC%88%98')[1]['courses'][0]['course_name'],'운영체제')
        self.assertEqual(listing('&page_size=0')[0],422)
        self.assertEqual(self.request('GET',base+'/courses?catalog_id='+seed.C2,cookie=cookie)[0],409)
        # Switching catalogs clears review but preserves the earlier course selection.
        change=self.patch(rid,cookie,4,{'catalog_id':seed.C2})
        self.assertEqual((change[1]['selection_revision'],change[1]['review_status']),(3,'unconfirmed'))
        updated=self.request('GET',base+'/courses?catalog_id='+seed.C2,cookie=cookie)[1]
        self.assertEqual(updated['out_of_scope_completed_courses'][0]['course_id'],selected)
        self.assertEqual(updated['selection_summary']['count'],0)
        outside={'catalog_id':seed.C2,'expected_selection_revision':3,'changes':[{'course_id':selected,'is_completed':True}]}
        self.assertEqual(self.request('PATCH',base+'/course-selections',outside,cookie)[0],422)
        outside['changes'][0]['is_completed']=False
        self.assertEqual(self.request('PATCH',base+'/course-selections',outside,cookie)[0],200)
        self.assertEqual(self.request('GET',base+'/courses?catalog_id='+seed.C2,cookie=cookie)[1]['out_of_scope_completed_courses'],[])

    def test_p2_course_identity_and_atomic_batch(self):
        seed_spec=importlib.util.spec_from_file_location('seed_identity', Path(__file__).resolve().parents[2] / 'app' / 'scripts' / 'seed_dev.py')
        seed=importlib.util.module_from_spec(seed_spec); seed_spec.loader.exec_module(seed); seed.seed()
        rid,cookie=self.create(); self.patch(rid,cookie,0,{'career_goal':'목표','university_id':seed.U,'department_id':seed.D,'catalog_id':seed.C1})
        base='/roadmap-inputs/'+rid
        same_id,old_same_name=seed.rows[0][0],seed.rows[2][0]
        invalid={'catalog_id':seed.C1,'expected_selection_revision':1,'changes':[{'course_id':same_id,'is_completed':True},{'course_id':'missing','is_completed':True}]}
        self.assertEqual(self.request('PATCH',base+'/course-selections',invalid,cookie)[0],422)
        self.assertEqual(self.request('GET',base+'/courses?catalog_id='+seed.C1,cookie=cookie)[1]['selection_summary']['count'],0)
        invalid['changes'][1]['course_id']=old_same_name
        self.assertEqual(self.request('PATCH',base+'/course-selections',invalid,cookie)[0],200)
        self.assertEqual(self.patch(rid,cookie,2,{'catalog_id':seed.C2})[0],200)
        result=self.request('GET',base+'/courses?catalog_id='+seed.C2,cookie=cookie)[1]
        same=next(c for c in result['courses'] if c['course_id']==same_id)
        other=next(c for c in result['courses'] if c['course_id']==seed.rows[6][0])
        self.assertTrue(same['is_completed'])
        self.assertFalse(other['is_completed'])
        self.assertEqual(result['out_of_scope_completed_courses'][0]['course_id'],old_same_name)

    def test_p2_parallel_requests(self):
        seed_spec=importlib.util.spec_from_file_location('seed_parallel', Path(__file__).resolve().parents[2] / 'app' / 'scripts' / 'seed_dev.py')
        seed=importlib.util.module_from_spec(seed_spec); seed_spec.loader.exec_module(seed); seed.seed()
        rid,cookie=self.create(); self.patch(rid,cookie,0,{'career_goal':'목표','university_id':seed.U,'department_id':seed.D,'catalog_id':seed.C1})
        endpoint='/roadmap-inputs/'+rid+'/course-selections'
        def toggle(item): return self.request('PATCH',endpoint,{'catalog_id':seed.C1,'expected_selection_revision':1,'changes':[{'course_id':item[0],'is_completed':True}]},cookie)[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(toggle,seed.rows[:2])),[200,409])


if __name__ == '__main__': unittest.main()

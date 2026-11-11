"""Isolated API upload -> worker -> extraction -> project analysis, no real APIs."""
from contextlib import closing
from pathlib import Path
import os
import sys
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unit'))
from fastapi.testclient import TestClient
from app.main import app
from repositories.plans import connect
from providers import google_vision_ocr
from services import document_ocr
from worker.documents import run_once
from project_experience_scenario import fake_extraction
from test_document_ocr import pdf, TEXT

# Even a forgotten mock cannot reach a Google endpoint in this child process.
from google.cloud import vision
vision.ImageAnnotatorClient = Mock(side_effect=AssertionError('No real Google clients in tests'))
with patch('app.main.start_worker',return_value=None), TestClient(app,headers={'Origin':'http://localhost:3000'}) as client:
    rid=client.post('/api/roadmap-inputs').json()['request_id']
    base='/api/roadmap-inputs/'+rid
    def listing(): return client.get(base+'/documents').json()
    def retry(did, revision=None):
        return client.post(base+'/documents/'+did+'/retry-extraction',json={'expected_input_revision':listing()['input_revision'] if revision is None else revision})
    response=client.post(base+'/documents',data={'expected_input_revision':'0'},files={'file':('scan.pdf',pdf(['scan']),'application/pdf')})
    assert response.status_code==201,response.text
    did=response.json()['document']['document_id']
    assert run_once()
    assert listing()['documents'][0]['extraction_status']=='needs_ocr'
    assert listing()['documents'][0]['retry_available'] is False
    assert retry(did).status_code==422
    os.environ['ROADMAP_OCR_PROVIDER']='google_vision'
    assert listing()['ocr']['reason']=='ocr_credentials_missing'
    assert retry(did).status_code==422
    provider=Mock(detect=Mock(return_value={'text':TEXT,'segments':[]}))
    with patch.object(document_ocr,'availability',return_value=None):
        os.environ['ROADMAP_OCR_MONTHLY_UNIT_LIMIT']='0'
        assert listing()['ocr']['reason']=='ocr_budget_exceeded'
        assert retry(did).status_code==429
        os.environ['ROADMAP_OCR_MONTHLY_UNIT_LIMIT']='900'
        assert retry(did,0).status_code==409
        assert retry(did).status_code==202
        assert run_once(ocr_provider=provider)
        detail=client.get(base+f'/documents/{did}/extractions/2').json()
        assert detail['extraction_status']=='ready' and detail['extracted_text']==TEXT
        assert detail['segments'][0]['page']==1 and detail['is_current_revision']
        assert listing()['documents'][0]['analysis_eligible']
        with patch('services.project_experience.extract_project_experiences',side_effect=fake_extraction) as analysis:
            response=client.post(base+'/project-experience-analysis',json={'expected_input_revision':listing()['input_revision']})
            assert response.status_code==200,response.text
            assert analysis.call_args.args[0]['extracted_text']==TEXT
        assert retry(did).status_code==202
        assert run_once(ocr_provider=provider)
        assert provider.detect.call_count==1
        assert client.get(base+f'/documents/{did}/extractions/2').json()['is_current_revision'] is False
        response=client.request('DELETE',base+f'/documents/{did}',json={'expected_input_revision':listing()['input_revision']})
        assert response.status_code==200,response.text
        assert run_once()
        assert client.get(base+f'/documents/{did}/extractions/3').status_code==410
    with closing(connect()) as db:
        assert db.execute('SELECT count(*) AS n FROM document_ocr_units').fetchone()['n']==1
        assert db.execute('SELECT result_json FROM document_ocr_units').fetchone()['result_json'] is None
print('OCR API workflow passed')

"""Standalone file intake; reuses the existing document parser without modifying it."""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'ai' / 'deps'))
sys.path.insert(0, str(ROOT / 'apps' / 'api' / 'app'))
from providers.document_parser import validate_file, extract, InvalidDocument

def create(input_path, directory, use_ocr=False, ocr_model='local'):
    data = json.loads(Path(input_path).read_text(encoding='utf-8-sig'))
    if not isinstance(data.get('career_goal'), str) or not data['career_goal'].strip(): raise ValueError('career_goal은 필수입니다.')
    for key in ('preparation_weeks',):
        if type(data.get(key)) is not int or data[key] < 1: raise ValueError(f'{key}는 양의 정수여야 합니다.')
    if data.get('year_level') is not None and (type(data['year_level']) is not int or data['year_level'] < 1): raise ValueError('year_level은 양의 정수여야 합니다.')
    for key in ('earned_credits', 'gpa', 'gpa_scale'):
        value = data.get(key)
        if value is not None and (type(value) not in (int, float) or not __import__('math').isfinite(value) or value < 0): raise ValueError(f'{key}는 0 이상의 숫자여야 합니다.')
    if data.get('gpa_scale') is not None and data['gpa_scale'] <= 0: raise ValueError('gpa_scale은 0보다 커야 합니다.')
    if data.get('gpa') is not None and (data.get('gpa_scale') is None or data['gpa'] > data['gpa_scale']): raise ValueError('GPA와 만점 기준을 확인하세요.')
    courses = data.get('completed_courses')
    status = data.get('course_history_status')
    if not isinstance(courses, list) or status not in ('provided', 'none', 'unknown') or (status == 'provided') != bool(courses): raise ValueError('이수 상태와 과목 목록을 확인하세요.')
    for course in courses:
        if not isinstance(course, dict) or not isinstance(course.get('course_name'), str) or not course['course_name'].strip(): raise ValueError('과목 이름을 확인하세요.')
        credits = course.get('credits')
        if credits is not None and (type(credits) not in (int, float) or not __import__('math').isfinite(credits) or credits < 0): raise ValueError('과목 학점은 0 이상의 숫자여야 합니다.')
    paths = data.pop('document_paths', None)
    if not isinstance(paths, list) or not 1 <= len(paths) <= 10:
        raise ValueError('document_paths에 파일을 1~10개 지정하세요.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'files').mkdir(exist_ok=True)
    request_id = str(uuid.uuid4())
    data['request_id'] = request_id
    data['plan_start_date'] = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    data['documents'] = []
    ocr_engine = None
    for file in paths:
        path = Path(file)
        if not path.is_absolute(): path = Path(input_path).resolve().parent / path
        raw = path.read_bytes()
        if len(raw) > 10 * 1024 * 1024: raise ValueError('파일은 최대 10MiB입니다.')
        did = str(uuid.uuid4())
        try:
            extension = path.suffix.lower().lstrip('.')
            if extension in ('png','jpg','jpeg'):
                if not use_ocr: raise InvalidDocument('이미지 입력에는 --ocr 옵션이 필요합니다.')
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(raw)) as image:
                    if image.format != ('PNG' if extension == 'png' else 'JPEG') or image.width * image.height > 20_000_000: raise InvalidDocument('이미지 형식 또는 크기를 확인하세요.')
                    image.verify()
                mime = 'image/png' if extension == 'png' else 'image/jpeg'
                result = {'text':'', 'segments':[], 'limitations':[], 'status':'needs_ocr', 'error_code':None}
            else:
                extension, mime = validate_file(path.name, raw)
                result = extract(extension, raw)
            if use_ocr and (extension in ('png','jpg','jpeg') or (extension in ('pdf','docx') and result['status'] in ('partial','needs_ocr','failed'))):
                if ocr_engine is None:
                    from local.ocr import LocalOCR
                    ocr_engine = LocalOCR(ocr_model)
                for number, extracted in ocr_engine.extract(extension, raw):
                    if not extracted.strip(): continue
                    prefix = '\n' if result['text'] else ''
                    start = len(result['text']) + len(prefix)
                    extracted = extracted[:max(0,1_000_000-start)]
                    result['text'] += prefix + extracted
                    if extracted:
                        location = {'page':number} if extension == 'pdf' else {'image_index':number}
                        result['segments'].append({'start':start,'end':start+len(extracted),'method':'ocr',**location})
                result['limitations'].append('OCR은 문자·순서가 부정확하거나 기존 본문과 중복될 수 있습니다. 읽힌 범위를 확인하세요.')
                result['ocr_model'] = ocr_model
                result['ocr_model_revision'] = 'ocr-v2' if ocr_model == 'local' else 'qota-ocr'
                result['status'] = 'partial' if result['text'].strip() else 'needs_ocr'
                result['error_code'] = None if result['text'].strip() else 'ocr_no_text'
        except InvalidDocument as error:
            mime = None
            result = {'text': '', 'segments': [], 'limitations': [str(error)], 'status': 'failed', 'error_code': 'invalid_file'}
        (directory / 'files' / did).write_bytes(raw)
        data['documents'].append({'document_id': did, 'original_filename': path.name, 'mime_type': mime,
            'file_size_bytes': len(raw), 'storage_key': did, 'extraction_status': result['status'],
            'extracted_text': result['text'], 'segments': result['segments'], 'limitations': result['limitations'],
            'error_code': result['error_code'], 'partial_confirmed': False, 'ocr_model': result.get('ocr_model'), 'ocr_model_revision': result.get('ocr_model_revision')})
    with sqlite3.connect(directory / 'intake.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, input_json TEXT NOT NULL)')
        db.execute('INSERT INTO requests VALUES (?, ?)', (request_id, json.dumps(data, ensure_ascii=False)))
    print(json.dumps(data, ensure_ascii=False, indent=2))

def export(directory, request_id, confirmed):
    with sqlite3.connect(Path(directory) / 'intake.sqlite3') as db:
        row = db.execute('SELECT input_json FROM requests WHERE request_id=?', (request_id,)).fetchone()
        if not row: raise ValueError('요청을 찾을 수 없습니다.')
        data = json.loads(row[0])
        partial_ids = {doc['document_id'] for doc in data['documents'] if doc['extraction_status'] == 'partial'}
        if not set(confirmed).issubset(partial_ids): raise ValueError('확인 ID는 해당 요청의 부분 추출 문서여야 합니다.')
        for doc in data['documents']:
            if doc['document_id'] in confirmed: doc['partial_confirmed'] = True
        db.execute('UPDATE requests SET input_json=? WHERE request_id=?', (json.dumps(data, ensure_ascii=False), request_id))
    print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    new = sub.add_parser('create'); new.add_argument('input'); new.add_argument('--storage', required=True); new.add_argument('--ocr', action='store_true'); new.add_argument('--ocr-model', choices=['local','open-source'], default='local')
    out = sub.add_parser('export'); out.add_argument('request_id'); out.add_argument('--storage', required=True); out.add_argument('--confirm', action='append', default=[])
    args = parser.parse_args()
    try:
        if args.action == 'create': create(args.input, args.storage, args.ocr, args.ocr_model)
        else: export(args.storage, args.request_id, args.confirm)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr); sys.exit(1)

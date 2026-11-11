"""Synthetic transcription of the reported ClassBridge facts, not the original PDF.

OCR paragraphs deliberately follow column/recognition order rather than row order.
Both PDF page coordinates and DOCX paragraph coordinates can be exercised.
"""
from services.project_experience_schemas import DocumentExperience


DETAILS = {
    'FastAPI': 'FastAPI REST API 9개 설계 및 구현',
    'PostgreSQL': 'PostgreSQL 테이블 6개 설계',
    'Redis': 'Redis 큐·재시도 구현',
    'PyMuPDF': 'PyMuPDF 문서 파싱 및 OCR 서비스 연동',
    'pytest': 'pytest 자동화 테스트 42개 작성',
}
ROWS = [
    ('Python 3.12', '직접 사용', ['Python']),
    ('FastAPI / Redis', '직접 구현', ['FastAPI', 'Redis']),
    ('PostgreSQL', '직접 설계', ['PostgreSQL']),
    ('Docker / GitHub Actions', '일부 설정', ['Docker', 'GitHub Actions']),
    ('Next.js / TypeScript', '팀원 담당', ['Next.js', 'TypeScript']),
]
ROLE_DESCRIPTION = '담당 역할: 백엔드 API 개발 및 OCR 작업 큐 설계'


def ocr_document(cells, coordinate='page'):
    text, segments = '', []
    for value, page, x, y, width in cells:
        start = len(text)
        text += value + '\n'
        segments.append({'start': start, 'end': len(text) - 1, coordinate: page,
                         'ocr_paragraph': len(segments) + 1, 'bbox': [[x, y], [x + width, y + 20]],
                         'source': 'google_vision'})
    return {'document_id': 'classbridge', 'extraction_revision': 1,
            'extracted_text': text, 'segments': segments}


def classbridge_document(coordinate='page'):
    cells = [('구분', 1, 20, 100, 70), ('언어', 1, 20, 140, 70), ('백엔드', 1, 20, 180, 70),
             ('기술 스택', 1, 150, 100, 100), ('본인 기여 여부', 1, 450, 100, 130)]
    cells += [(tech, 1, 150, 140 + i * 40, 260) for i, (tech, _, _) in enumerate(ROWS)]
    # The nearest flattened contribution to FastAPI is deliberately the wrong row.
    cells += [(ROWS[i][1], 1, 450, 140 + i * 40, 100) for i in (4, 0, 3, 1, 2)]
    cells += [('본인이 직접 수행한 작업', 2, 50, 50, 300)]
    cells += [(DETAILS[name], 2, 70, 90 + i * 40, 450) for i, name in enumerate(DETAILS)]
    cells += [('팀 전체 성과', 2, 50, 310, 300),
              ('팀 전체 서비스 테스트: 사용자 48명', 2, 70, 350, 450),
              ('Playwright 서비스 테스트 48개 작성', 2, 70, 390, 450)]
    return ocr_document(cells, coordinate)


def classbridge_original_order_document(coordinate='page'):
    """Reported source order: heading, role description, ①–⑤, then the table."""
    cells = [('본인이 직접 수행한 작업', 1, 50, 50, 300),
             (ROLE_DESCRIPTION, 1, 70, 90, 500)]
    cells += [(marker + ' ' + detail, 1, 70, 130 + i * 40, 450)
              for i, (marker, detail) in enumerate(zip('①②③④⑤', DETAILS.values()))]
    cells += [('구분', 1, 20, 330, 70), ('기술 스택', 1, 150, 330, 100),
              ('본인 기여 여부', 1, 450, 330, 130)]
    cells += [(tech, 1, 150, 370 + i * 40, 260) for i, (tech, _, _) in enumerate(ROWS)]
    cells += [(ROWS[i][1], 1, 450, 370 + i * 40, 100) for i in (4, 0, 3, 1, 2)]
    cells += [('Playwright 서비스 테스트 48개 작성', 1, 70, 570, 450)]
    return ocr_document(cells, coordinate)


def response(document, items):
    return DocumentExperience(document_id=document['document_id'],
        extraction_revision=document['extraction_revision'], experiences=items)


def candidate(name, quote, **changes):
    return {'skill_name': name, 'category': 'other', 'activity': '직접 구현',
            'contribution_scope': 'personal', 'evidence_text': quote, **changes}


def classbridge_extraction(document):
    items = [candidate(name, tech, activity='전체 인프라 구축' if label == '일부 설정' else label)
             for tech, label, names in ROWS for name in names]
    items += [candidate(name, quote, role='팀장', output='완성된 서비스',
                        activity='팀장으로 API 12개 구현' if name == 'FastAPI' else '직접 구현')
              for name, quote in DETAILS.items()]
    return response(document, items)

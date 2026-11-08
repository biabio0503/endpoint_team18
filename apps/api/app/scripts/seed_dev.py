"""Idempotently load fictional development references, never official curricula."""
from contextlib import closing
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repositories.p1 import connect, migrate
from config import DB_BACKEND

U='10000000-0000-4000-8000-000000000001'
D='20000000-0000-4000-8000-000000000001'
C1='30000000-0000-4000-8000-000000000001'
C2='30000000-0000-4000-8000-000000000002'
rows=[('40000000-0000-4000-8000-000000000001','프로그래밍 기초','DEV101',3,'전공필수',1,'1학기'),('40000000-0000-4000-8000-000000000002','자료구조','DEV201',3,'전공필수',2,'1학기'),('40000000-0000-4000-8000-000000000003','데이터베이스','DEV202',3,'전공선택',2,'2학기'),('40000000-0000-4000-8000-000000000004','소프트웨어 설계','DEV301',None,'전공선택',3,'1학기'),('40000000-0000-4000-8000-000000000005','운영체제','DEV302',3,'전공필수',3,'2학기'),('40000000-0000-4000-8000-000000000006','프로젝트 실습','DEV401',2,'전공선택',4,'1학기'),('40000000-0000-4000-8000-000000000007','데이터베이스','DEV999',3,'전공선택',3,'2학기')]

def seed(only_if_empty=False):
    if DB_BACKEND != 'sqlite':
        raise RuntimeError('개발용 seed는 SQLite에서만 사용할 수 있습니다.')
    migrate()
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        if only_if_empty and db.execute('SELECT 1 FROM universities LIMIT 1').fetchone():
            db.commit()
            return False
        db.execute('INSERT OR IGNORE INTO universities VALUES(?,?,1)',(U,'가상대학교 (개발용 예시)'))
        db.execute('INSERT OR IGNORE INTO departments VALUES(?,?,?,1)',(D,U,'컴퓨터공학과 (가상 예시)'))
        for cid, label in ((C1,'가상 교육과정 A (개발용)'),(C2,'가상 교육과정 B (개발용)')):
            db.execute('INSERT OR IGNORE INTO course_catalogs VALUES(?,?,NULL,?,?,?,?,?,?,NULL,1)',(cid,D,label,'개발·테스트용으로 직접 만든 가상 과목 목록이며 실제 교육과정이 아닙니다.','unknown','팀18 개발용 가상 예시 데이터',None,'2026-11-07T00:00:00+00:00'))
        for course_id,name,code,credits,category,year,term in rows:
            db.execute('INSERT OR IGNORE INTO courses(course_id,university_id,canonical_name,source_course_code) VALUES(?,?,?,?)',(course_id,U,name,code))
            for cid in ([C1,C2] if course_id.endswith('000000000001') else [C1] if not course_id.endswith('000000000007') else [C2]):
                db.execute('INSERT OR IGNORE INTO catalog_courses(catalog_id,course_id,course_name,course_code,credits,category,recommended_year,recommended_term) VALUES(?,?,?,?,?,?,?,?)',(cid,course_id,name,code,credits,category,year,term))
        db.commit()
    print('가상 개발용 과목 자료를 준비했습니다. 실제 교육과정이 아닙니다.')
    return True

if __name__=='__main__': seed()

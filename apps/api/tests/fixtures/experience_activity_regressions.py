"""Fixed incident inputs, not captured production documents or model responses."""
from services.project_experience_schemas import DocumentExperience

EXPERIENCES = [
    ('matplotlib', '저는 matplotlib으로 요일별 이용률 그래프를 만들었습니다.'),
    ('Figma', '저는 Figma로 예약 변경 화면의 클릭형 프로토타입을 만들었습니다.'),
    ('사용성 테스트', '저는 사용성 테스트를 진행하여 예약 취소 버튼을 찾지 못하는 지점을 기록했습니다.'),
    ('사용자 인터뷰', '저는 사용자 인터뷰를 진행하고 반복되는 불편을 분석표에 정리했습니다.'),
    ('React', '팀원 정우는 React로 예약 화면을 실제 서비스에 구현했습니다.'),
    ('Framer', 'Framer는 다음 학기에 공부할 예정이며, 이 프로젝트에서는 사용하지 않았습니다.'),
]
PROJECT_TEXT = '\n'.join(quote for _, quote in EXPERIENCES)


def fixed_extraction(document):
    # Deliberately overclaims both negative controls as personal. The server must
    # establish contribution from the source independently of the model's label.
    return DocumentExperience(document_id=document['document_id'],
        extraction_revision=document['extraction_revision'], experiences=[
            {'skill_name': name, 'category': 'other', 'activity': quote,
             'contribution_scope': 'personal', 'evidence_text': quote}
            for name, quote in EXPERIENCES])


NEGATION_CASES = [
    ('저는 사용자 인터뷰를 진행했습니다.', {'사용자 인터뷰': 'personal'}),
    ('저는 사용자 인터뷰를 진행한 적이 없습니다.', {'사용자 인터뷰': 'unknown'}),
    ('저는 사용자 인터뷰를 진행해 사용자가 예약 버튼을 찾지 못하는 지점을 기록했습니다.',
     {'사용자 인터뷰': 'personal'}),
    ('저는 사용자 인터뷰를 진행했지만 Figma로 프로토타입을 만든 적은 없습니다.',
     {'사용자 인터뷰': 'personal', 'Figma': 'unknown'}),
]

# Minimal reproductions from the 884c761 review. Quotes deliberately omit the
# predicate/subject, or include a different activity's subject and future plan.
CLAUSE_CASES = [
    ('clipped_sql_negation', '제가 SQL을 사용하지 않았습니다.', 'SQL', '제가 SQL을 사용', 'unknown'),
    ('never_tried', '저는 사용자 인터뷰를 진행해 보지 않았습니다.', '사용자 인터뷰', '사용자 인터뷰를 진행', 'unknown'),
    ('other_personal_clause', '민수는 Docker를 배포했고 저는 Python 코드를 작성했습니다.', 'Docker', 'Docker를 배포', 'unknown'),
    ('other_team_clause', '팀원 민수는 Docker를 배포했고 저는 Python 코드를 작성했습니다.', 'Python', 'Python 코드', 'personal'),
    ('other_future_clause', '저는 Python으로 데이터를 분석했고 Docker는 향후 사용할 계획입니다.', 'Python', 'Python으로 데이터를 분석', 'personal'),
]


def negation_extraction(document):
    text = document['extracted_text']
    scopes = next(scopes for quote, scopes in NEGATION_CASES if quote == text)
    # Both candidates in the mixed case deliberately cite the entire sentence.
    return DocumentExperience(document_id=document['document_id'],
        extraction_revision=document['extraction_revision'], experiences=[
            {'skill_name': name, 'category': 'other', 'activity': text,
             'contribution_scope': 'personal', 'evidence_text': text}
            for name in scopes])


FRONTEND = {'career_goal': '사용자가 편하게 쓸 수 있는 웹을 만들고 싶습니다.', 'target_role': '프론트엔드 개발자'}
BIKE_DATA = {'career_goal': '공공 자전거 수요를 분석하고 싶습니다.', 'target_role': '데이터 분석가'}


def postings():
    return [{'id': str(i), 'kind': 'competition', 'title': title, 'category': category,
             'target': '대학생', 'period': '상시 접수', 'host': '고정 테스트 공고',
             'url': f'https://www.contestkorea.com/sub/view.php?str_no={i}'}
            for i, (title, category) in enumerate([
                ('누구나 할 수 있는 쇼핑 숏폼 부업 강의', '교육'),
                ('전국 자전거 대행진', '스포츠'),
                ('공공데이터 활용 경진대회', '아이디어'),
                ('자전거 수요 데이터 분석 경진대회', '공모전'),
            ])]

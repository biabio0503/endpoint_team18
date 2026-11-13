"""Create fictional smoke-test examples, never suitable as production training data."""
import json
from pathlib import Path
from prompt import make_prompt

roles = [('데이터 분석가', '데이터 정리', 'Python', '통계 기초'), ('웹 개발자', '화면 구현', 'JavaScript', '웹 기초'), ('백엔드 개발자', 'API 구현', 'Python', '서버 기초'), ('보안 분석가', '로그 점검', 'Linux', '네트워크 기초'), ('기획자', '요구사항 정리', '문서 작성', '사용자 조사'), ('앱 개발자', '화면 설계', 'Kotlin', '모바일 기초')]
target = Path(__file__).with_name('demo.jsonl')
with target.open('w', encoding='utf-8') as f:
    for index, (role, activity, tool, topic) in enumerate(roles):
        for week in (4, 6, 8, 12):
            for status in ('unknown', 'none', 'provided'):
                quote = f'팀 프로젝트에서 {tool}을 사용해 {activity}를 수행했습니다.'
                courses = [{'course_name': '기초 수업', 'credits': 3}] if status == 'provided' else []
                data = {'career_goal': role + ' 준비', 'target_role': role, 'preparation_weeks': week, 'course_history_status': status, 'completed_courses': courses, 'documents': [{'document_id': f'doc-{index}', 'extraction_status': 'ready', 'extracted_text': quote}]}
                result = {'summary': f'{role} 준비를 위한 학습을 제안합니다.', 'experiences': [{'project': '팀 프로젝트', 'description': activity, 'document_id': f'doc-{index}', 'quote': quote}], 'questions': ['담당한 역할을 더 자세히 알려주세요.'], 'roadmap': [{'start_week': 1, 'end_week': week, 'goal': topic, 'actions': [f'{topic}를 학습하고 작은 결과물을 만듭니다.'], 'reason': '목표 직무의 기초 학습을 위한 제안입니다.'}], 'course_suggestions': [topic], 'limitations': ['가상 예시이며 실제 수강 가능 여부는 확인해야 합니다.']}
                row = {'messages': [{'role': 'user', 'content': make_prompt(data)}, {'role': 'assistant', 'content': json.dumps(result, ensure_ascii=False)}]}
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
print(f'가상 테스트 데이터 {len(roles) * 12}건 생성: {target}')

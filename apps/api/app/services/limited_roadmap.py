"""No provider call or invented job/course claims when external evidence is absent."""


def limited_roadmap(basis):
    profile = basis['profile']
    goal = profile['career_goal'] or '진로 목표'
    role = profile['target_role'] or '관심 직무'
    documents = basis['project_documents']
    confirmed = basis['review_status'] in ('confirmed', 'partial')
    items = [
        ('goal', '목표와 직무 범위 확인', f'저장한 목표 “{goal}”와 “{role}”에서 관심 업무를 구체적으로 적어 주세요.',
         '관심 업무와 확인할 질문을 각각 한 가지 이상 기록함', '목표·관심 업무 메모'),
        ('experience', '본인 수행 경험 정리',
         f'현재 분석된 문서 {len(documents)}개의 본인 역할과 수행 내용을 확인하고, 근거가 없는 경험은 미확인으로 남겨 주세요.' if documents else '본인이 수행한 프로젝트가 있다면 역할·행동·결과를 정리해 주세요. 자료가 없으면 미확인으로 남겨 주세요.',
         '본인 역할·행동·결과 또는 자료 미확인 상태를 기록함', '본인 경험 확인 메모'),
        ('courses', '학업 정보와 다음 분석 준비',
         '확인한 이수 목록과 목록 밖 기록을 검토하고, 직무 분석을 다시 실행한 뒤 구체적인 학습 활동을 결정해 주세요.' if confirmed else '기본 정보와 이수 과목의 확인 상태를 검토하고, 직무 분석이 가능해지면 구체적인 학습 활동을 결정해 주세요.',
         '학업 정보의 확인 범위와 추가로 확인할 자료를 기록함', '학업 정보 확인 메모'),
    ]
    limitation = '검증된 채용 기술 근거가 없어 입력 정리를 돕는 제한 안내입니다. 직무 기술·학습 우선순위·수강 후보는 판단하지 않았습니다.'
    return {
        'status': 'partial', 'generation_mode': 'limited_guidance',
        'career_goal': profile['career_goal'], 'target_role': profile['target_role'],
        'preparation_summary': {'confirmed_skills': [], 'skills_to_verify': [], 'learning_candidates': []},
        'preparation_items': [], 'evidence': {}, 'recommended_courses': [],
        'roadmap': [{
            'step_id': key, 'order': i, 'title': title, 'purpose': '현재 입력과 확인 범위 정리',
            'reason': '저장된 목표·문서·이수 확인 상태에 따른 안내', 'related_skills': [], 'skill_targets': [],
            'related_course_ids': [], 'depends_on': [items[i-2][0]] if i > 1 else [], 'evidence_refs': [],
            'limitations': limitation, 'recommendation_kind': 'guidance',
            'tasks': [{'task_id': key + '-review', 'task_type': 'document', 'title': title, 'action': action,
                       'completion_criteria': criteria, 'deliverable': deliverable}],
        } for i, (key, title, action, criteria, deliverable) in enumerate(items, 1)],
        'limitations': [limitation, *basis['limitations']], 'course_status': 'evidence_unavailable',
        'basis': {k: basis[k] for k in ('catalog', 'review_status', 'course_selection_revision', 'reviewed_at',
            'outside_completed_courses', 'job_snapshot_id', 'job_status', 'job_analyzed_at', 'job_summary',
            'project_status', 'project_version', 'project_documents', 'excluded_documents', 'document_basis')},
    }

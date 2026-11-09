// Browser-only synthetic fixtures. No provider, authentication service or database is contacted.
export function installRoadmapMock() {
 localStorage.setItem('sb-job-skills-test-auth-token', JSON.stringify({ access_token: 'test.token.value', refresh_token: 'test-refresh', expires_at: Math.floor(Date.now()/1000)+3600, expires_in: 3600, token_type: 'bearer', user: { id: 'test-user' } }));
 sessionStorage.setItem('roadmap_request_id', 'test-plan'); sessionStorage.setItem('roadmap_request_owner', 'test-user');
 const m = window.mockRoadmap = JSON.parse(sessionStorage.getItem('roadmap-test-state') || 'null') || { revision: 1, posts: 0, patches: 0, runs: [], sql: 'no_experience', completed: false, removed: false, jobAvailable: false };
 const persist = () => sessionStorage.setItem('roadmap-test-state', JSON.stringify(m));
 const metadata = r => ({ run_id: r.run_id, status: r.status, input_revision: r.input_revision, current_input_revision: m.revision, created_at: r.created_at, model_name: 'test-model', rules_version: 'test-rules', is_stale: r.input_revision !== m.revision, details_restricted: m.removed });
 const view = r => m.removed ? metadata(r) : { ...structuredClone(r), ...metadata(r) };
 const create = () => {
  const catalog = { source_name: '합성 브라우저 테스트 목록', scope_description: '테스트 전용', retrieved_at: '2026-11-09T00:00:00Z', completeness_status: 'complete' };
  const course = { course_id: 'db-course', course_name: '데이터베이스', course_code: 'TEST-DB', credits: 3, recommended_year: 2, recommended_term: '2학기', related_skills: ['SQL'], evidence_refs: ['comparison:sql'], reason: 'SQL 조회 개념과 관련된 수강 후보', personalization_reason: m.sql + ' 응답 반영', completion_state: 'unconfirmed', recommendation_confidence: 'limited', description_basis: 'name_inference', course_evidence: '데이터베이스', limitations: '과목명 기반 추론입니다.', availability_notice: '실제 개설 여부 확인 필요' };
  const r = { run_id: 'run-' + m.posts, status: 'partial', input_revision: m.revision, created_at: '2026-11-09T06:00:0' + m.posts + 'Z', career_goal: '데이터 분석', target_role: '데이터 분석가',
   preparation_summary: { confirmed_skills: ['Python'], skills_to_verify: m.sql === 'no_experience' ? [] : ['SQL'], learning_candidates: m.sql === 'no_experience' ? ['SQL'] : [] },
   preparation_items: [{ skill_name: 'SQL', student_status: m.sql, reason: '사용자 응답을 반영했습니다.', comparison_ref: 'comparison:sql', job_refs: ['job:sql'], project_refs: [] }],
   evidence: { 'comparison:sql': { skill_name: 'SQL', kind: 'comparison', student_status: m.sql, reason: '사용자가 답변한 상태', job_refs: ['job:sql'], project_refs: [] }, 'job:sql': { skill_name: 'SQL', kind: 'job', evidence_text: 'SQL is required.', source_url: 'https://himalayas.app/jobs/test' } },
   basis: { catalog, review_status: 'unconfirmed', outside_completed_courses: [], job_summary: { analyzed_jobs: 2 }, project_documents: [], job_snapshot_id: 'test-snapshot', job_analyzed_at: '2026-11-09T00:00:00Z' },
   course_status: 'provisional', recommended_courses: m.completed ? [] : [course], limitations: ['해외 원격근무 표본입니다.', '경험 자료 부족은 경험 없음을 뜻하지 않습니다.'], progress: { completed: 0, total: 3 },
   roadmap: [1,2,3].map(i => ({ step_id: 'step-' + i, order: i, title: (m.sql === 'no_experience' ? 'SQL 학습' : 'SQL 경험 확인') + ' ' + i, purpose: '수행 가능한 활동', reason: m.sql + ' 응답 기준', related_skills: ['SQL'], related_course_ids: m.completed ? [] : ['db-course'], depends_on: i > 1 ? ['step-' + (i-1)] : [], evidence_refs: ['comparison:sql'], limitations: '추천 의견입니다.', tasks: [{ task_id: 'task-' + i, title: '실행 작업 ' + i, action: '검토 자료를 정리한다.', completion_criteria: '검토 가능한 파일을 남긴다.', deliverable: '기록 파일', is_completed: false, progress_version: 0 }] })) };
  m.runs.unshift(r); return r;
 };
 const nativeFetch = window.fetch;
 window.fetch = async (input, options = {}) => {
  const url = String(input);
  if (!url.includes('/api/')) return nativeFetch(input, options);
  const json = (data, status = 200) => { persist(); return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }); };
  const body = options.body ? JSON.parse(options.body) : {};
  if (url.endsWith('/roadmap')) {
   if (options.method === 'POST') {
    if (!m.jobAvailable) return json({ error: 'needs_job_analysis', message: '직무 분석을 먼저 실행해 주세요.' }, 422);
    if (m.limited) return json({ error: 'gemini_rate_limited', message: 'Gemini 사용량 제한에 도달했습니다.' }, 503);
    if (m.conflict) { m.revision++; m.conflict = false; return json({ error: 'revision_conflict', message: '생성 중 입력이 변경되었습니다.' }, 409); }
    if (body.expected_input_revision !== m.revision) return json({ error: 'revision_conflict', message: '입력이 변경되었습니다.' }, 409);
    const existing = m.runs.find(r => r.input_revision === m.revision);
    if (existing && !body.refresh) return json(view(existing));
    m.posts++; return json(view(create()), 201);
   }
   return json(m.runs.length ? view(m.runs[0]) : { status: m.jobAvailable ? 'not_started' : 'needs_job_analysis', input_revision: m.revision });
  }
  if (url.endsWith('/roadmaps')) return json({ runs: m.runs.map(metadata) });
  if (url.includes('/roadmaps/')) {
   const parts = url.split('/'), id = parts[parts.indexOf('roadmaps') + 1], record = m.runs.find(r => r.run_id === id);
   if (options.method === 'PATCH') {
    const task = record.roadmap.flatMap(s => s.tasks).find(t => t.task_id === parts.at(-1));
    if (m.progressConflict) { m.progressConflict = false; task.progress_version++; return json({ error: 'progress_conflict', message: '다른 화면에서 진행 상태를 변경했습니다.' }, 409); }
    task.is_completed = body.is_completed; task.progress_version++; m.patches++;
    record.progress.completed = record.roadmap.flatMap(s => s.tasks).filter(t => t.is_completed).length;
   }
   return json(view(record));
  }
  return json({ request_id: 'test-plan', input_revision: m.revision, input: { career_goal: '데이터 분석' } });
 };
}

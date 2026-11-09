export function roadmapErrorMessage(error) {
 const code = error?.code || error?.error_code;
 let message = error?.message || '이 실행은 결과를 생성하지 못했습니다. 이전 저장 결과와 완료 체크는 유지됩니다.';
 if (code === 'gemini_invalid_response') {
  const detail = error.detailCode || error.error_detail_code || '';
  const topic = detail.startsWith('schema_') ? '응답 형식' :
   detail.startsWith('course_') || detail.startsWith('related_course_') ? '추천 과목과 과목 근거' :
   detail.startsWith('evidence_') || detail.startsWith('skill_') ? '추천 기술과 근거' :
   detail.startsWith('experience_') || detail.startsWith('confirmed_experience_') || detail === 'task_type_mismatch' ? '경험 상태와 활동 유형' :
   detail.startsWith('step_') || detail.startsWith('dependency_') || detail.startsWith('task_') ? '실행 순서와 작업 내용' : '추천 내용';
  message = `생성된 로드맵이 ${topic} 검증을 통과하지 못해 저장하지 않았습니다. 이전 로드맵과 완료 체크는 유지됩니다. 잠시 후 다시 생성해 주세요. 반복되면 실행 ID를 알려 주세요.`;
 }
 const runId = error?.runId || error?.run_id;
 return runId ? `${message} 실행 ID: ${runId}` : message;
}

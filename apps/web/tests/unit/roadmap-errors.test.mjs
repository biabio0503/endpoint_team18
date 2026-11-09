import { test } from 'node:test';
import assert from 'node:assert/strict';
import { roadmapErrorMessage } from '../../src/features/roadmap/roadmapErrors.mjs';

test('validation failures explain preservation and give the failed run ID', () => {
 const message = roadmapErrorMessage({ code: 'gemini_invalid_response', detailCode: 'experience_status_mismatch', runId: 'failed-run' });
 assert.match(message, /경험 상태와 활동 유형/);
 assert.match(message, /이전 로드맵과 완료 체크는 유지/);
 assert.match(message, /실행 ID: failed-run/);
 assert.doesNotMatch(message, /experience_status_mismatch/);
});

test('history handles detailed and legacy failures without needing a schema migration', () => {
 assert.match(roadmapErrorMessage({ error_code: 'gemini_invalid_response', error_detail_code: 'course_evidence_mismatch', run_id: 'run' }), /추천 과목과 과목 근거/);
 assert.match(roadmapErrorMessage({ error_code: 'gemini_invalid_response', run_id: 'legacy' }), /실행 ID: legacy/);
 assert.match(roadmapErrorMessage({ error_code: 'generation_expired', run_id: 'expired' }), /이전 저장 결과와 완료 체크는 유지/);
 assert.equal(roadmapErrorMessage({ message: '잠시 기다려 주세요.', code: 'ai_cooldown' }), '잠시 기다려 주세요.');
});

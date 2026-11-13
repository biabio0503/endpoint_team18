import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { generateRoadmap, validateInput, validateResult } from './roadmap.mjs';

const input = JSON.parse(await readFile(new URL('../sample-input.json', import.meta.url), 'utf8'));
const answer = {
  summary: '데이터 분석 준비',
  experiences: [{ project: '교내 식당 이용 분석', description: '설문 데이터를 정리함', document_id: 'example-document-1', quote: '설문 데이터를 정리하고' }],
  questions: ['담당한 구체적인 분석 과정은 무엇인가요?'],
  roadmap: [{ start_week: 1, end_week: 12, goal: '분석 연습', actions: ['분석 결과 정리'], reason: '입력한 목표와 관련됨' }],
  course_suggestions: ['통계 기초'], limitations: ['실제 수강 가능 여부 확인 필요']
};

test('샘플 입력이 Gemini 요청에 전달되고 결과가 반환된다', async () => {
  let request;
  const result = await generateRoadmap(input, { apiKey: 'test-key', fetchImpl: async (url, options) => {
    request = { url, ...options, body: JSON.parse(options.body) };
    return { ok: true, json: async () => ({ candidates: [{ finishReason: 'STOP', content: { parts: [{ text: JSON.stringify(answer) }] } }] }) };
  } });
  assert.equal(request.headers['x-goog-api-key'], 'test-key');
  assert.deepEqual(JSON.parse(request.body.contents[0].parts[0].text), input);
  assert.deepEqual(result, answer);
});

test('잘못된 이수 상태, 확인되지 않은 문서, 허위 근거를 거절한다', () => {
  assert.throws(() => validateInput({ ...input, course_history_status: 'unknown' }));
  assert.throws(() => validateInput({ ...input, documents: [{ ...input.documents[0], extraction_status: 'partial' }] }));
  assert.throws(() => validateResult({ ...answer, experiences: [{ ...answer.experiences[0], quote: '없는 인용문' }] }, input));
  assert.throws(() => validateResult({ ...answer, roadmap: [{ ...answer.roadmap[0], end_week: 13 }] }, input));
});

test('OCR 줄바꿈만 다른 인용은 실제 원문으로 복원한다', () => {
  const source = { ...input, documents: [{ ...input.documents[0], extracted_text: '사용자\n인터뷰\n프로젝트' }] };
  const result = { ...answer, experiences: [{ ...answer.experiences[0], quote: '사용자 인터뷰 프로젝트' }] };
  assert.equal(validateResult(result, source).experiences[0].quote, '사용자\n인터뷰\n프로젝트');
  assert.throws(() => validateResult({ ...answer, experiences: [{ ...answer.experiences[0], quote: '사용자 인터뷰 성공' }] }, source));
});

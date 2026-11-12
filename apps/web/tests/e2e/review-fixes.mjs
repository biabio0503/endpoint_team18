// Real local API/DB/parser. Start review_fixes_ui_server.py and Next on :15102.
// PLAYWRIGHT_MODULE may point to an existing Playwright installation.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.JOB_SKILLS_WEB_ORIGIN || 'http://localhost:15102';
const browser = await chromium.launch({ executablePath: process.env.P5_BROWSER, headless: true });
const failures = [], reports = [];

async function scenario(name, run) {
 const context = await browser.newContext();
 const external = [], errors = [];
 await context.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (['localhost', '127.0.0.1'].includes(url.hostname)) return route.continue();
  if (url.hostname === 'job-skills-test.supabase.co') return route.fulfill({ json: {
   access_token: 'test.token.value', refresh_token: 'test-refresh', expires_in: 3600, token_type: 'bearer',
   user: { id: '12345678-0000-4000-8000-000000000001', is_anonymous: true, aud: 'authenticated' },
  } });
  external.push(url.origin); await route.abort();
 });
 context.on('page', page => { page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message)); });
 try {
  await run(context);
  assert.deepEqual(external, []); assert.deepEqual(errors, []);
  reports.push({ name, status: 'pass', external_requests: external.length });
 } catch (error) {
  failures.push(error); reports.push({ name, status: 'fail', message: error.message });
 } finally { await context.close(); }
}
const button = (page, name) => page.getByRole('button', { name, exact: true });
const waitText = (page, text) => page.waitForFunction(t => document.body.innerText.includes(t), text);
const json = async response => { assert.equal(response.status(), 200, await response.text()); return response.json(); };
async function guest(context) {
 const page = await context.newPage();
 await page.goto(origin); await button(page, '로그인 없이 시작하기').click(); await button(page, '작성하기').click();
 await page.waitForURL('**/input/basic');
 await page.locator('[name=career_goal]').fill('공공데이터 분석을 하고 싶습니다.');
 await page.locator('[name=target_role]').fill('Data Analyst');
 await page.locator('[name=university_id]').selectOption('10000000-0000-4000-8000-000000000001');
 await page.locator('[name=department_id]').selectOption('20000000-0000-4000-8000-000000000001');
 await page.locator('[name=catalog_id]').selectOption('30000000-0000-4000-8000-000000000001');
 await page.locator('[name=year_level]').selectOption('2');
 await button(page, '저장 후 다음: 프로젝트 문서').click(); await page.waitForURL('**/input/documents');
 await waitText(page, '등록된 문서가 없습니다.');
 const id = await page.evaluate(() => sessionStorage.getItem('roadmap_request_id'));
 return { page, base: `${origin}/api/roadmap-inputs/${id}` };
}

try {
 await scenario('new guest skips documents, selects courses, saves limited guidance', async context => {
  const { page, base } = await guest(context);
  const before = await json(await page.request.get(base));
  await button(page, '문서 없이 계속: 이수 과목').click(); await page.waitForURL('**/input/courses');
  assert.equal((await json(await page.request.get(base))).input_revision, before.input_revision);
  await page.getByRole('switch', { name: /프로그래밍 기초/ }).click();
  await waitText(page, '이수 선택이 저장되었습니다.');
  await button(page, '이수 선택 확인 완료').click(); await waitText(page, '현재 목록 전체의 확인 상태가 저장되었습니다.');
  await button(page, '다음: 분석 내용 확인').click(); await page.waitForURL('**/input/review');
  const comparison = await json(await page.request.get(base + '/skill-comparison'));
  assert.equal(comparison.project_analysis.status, 'no_documents');
  assert.deepEqual(comparison.project_analysis.experiences, []);
  assert.ok(comparison.comparisons.every(c => c.student_status !== 'no_experience'));
  await page.getByRole('link', { name: '다음: 결과 화면에서 직무 분석·로드맵 생성 →' }).click();
  await button(page, '제한 안내 로드맵 생성').click(); await waitText(page, '작업 완료 0 / 3개');
  const saved = await json(await page.request.get(base + '/roadmap'));
  assert.equal(saved.generation_mode, 'limited_guidance');
  await page.reload(); await waitText(page, '생성 처리 완료 시각');
  await page.getByRole('tab', { name: '공모전·대외활동', exact: true }).click();
  await waitText(page, 'SQL 공공데이터 분석 경진대회');
  assert.equal((await json(await page.request.get(base + '/roadmap'))).run_id, saved.run_id);
 });

 await scenario('failed extraction survives skip and can be retried', async context => {
  const { page, base } = await guest(context);
  await page.getByLabel('프로젝트 문서 선택').setInputFiles({ name: 'failed.txt', mimeType: 'text/plain', buffer: Buffer.from('LOCAL_EXTRACTION_FAILURE') });
  await waitText(page, '읽기 실패 · 분석 제외');
  const before = await json(await page.request.get(base + '/documents'));
  const doc = before.documents[0]; assert.equal(doc.extraction_status, 'failed'); assert.ok(doc.extraction_error_code);
  await button(page, '문서 없이 계속: 이수 과목').click(); await page.waitForURL('**/input/courses');
  const after = await json(await page.request.get(base + '/documents'));
  assert.deepEqual(after.documents, before.documents); assert.equal(after.input_revision, before.input_revision);
  await page.goto(origin + '/input/documents'); await waitText(page, '읽기 실패 · 분석 제외');
  const retry = page.waitForResponse(r => r.url().endsWith('/retry-extraction') && r.request().method() === 'POST');
  await button(page, '다시 읽기').click(); assert.equal((await retry).status(), 202);
  await page.waitForFunction(revision => [...document.querySelectorAll('tbody tr')].some(row =>
   row.innerText.includes(`추출 버전 ${revision}`) && row.innerText.includes('읽기 실패 · 분석 제외')), doc.extraction_revision + 1);
  const retried = (await json(await page.request.get(base + '/documents'))).documents[0];
  assert.equal(retried.document_id, doc.document_id); assert.equal(retried.extraction_revision, doc.extraction_revision + 1);
  assert.ok(retried.extraction_error_code);
 });

 await scenario('two tabs refresh changed evidence and reuse preserved evidence', async context => {
  const { page: result, base } = await guest(context);
  await result.getByLabel('프로젝트 문서 선택').setInputFiles({ name: 'project.txt', mimeType: 'text/plain', buffer: Buffer.from('제가 SQL로 데이터 조회 쿼리를 작성했습니다.') });
  await waitText(result, '읽기 완료 · 분석 포함 가능');
  await result.goto(origin + '/input/review'); await button(result, '프로젝트 경험 분석 실행').click();
  await result.locator('.skill-card h3').getByText('SQL', { exact: true }).waitFor();
  await button(result, '맞아요').click(); await waitText(result, '본인 경험으로 확인');
  const editor = await context.newPage();
  await editor.goto(origin); const session = await result.evaluate(() => Object.fromEntries(Object.entries(sessionStorage)));
  await editor.evaluate(values => { for (const [key, value] of Object.entries(values)) sessionStorage.setItem(key, value); }, session);
  await editor.goto(origin + '/input/review'); await button(editor, '프로젝트 경험 재분석').waitFor();
  await result.goto(origin + '/result'); await result.getByRole('tab', { name: '공모전·대외활동', exact: true }).click();
  await waitText(result, '확인한 프로젝트 경험');
  let activityCalls = 0;
  result.on('request', request => { if (request.url().endsWith('/activities')) activityCalls++; });
  const focus = async () => {
   const checked = result.waitForResponse(r => r.url() === base && r.request().method() === 'GET');
   await result.bringToFront(); await result.evaluate(() => window.dispatchEvent(new Event('focus')));
   await checked;
   await result.waitForFunction(() => document.querySelector('.activity-recommendations')?.getAttribute('aria-busy') === 'false');
  };
  const revision = (await json(await result.request.get(base))).input_revision;
  await editor.bringToFront();
  const refreshed = editor.waitForResponse(r => r.url().endsWith('/project-experience-analysis') && r.request().method() === 'POST');
  await button(editor, '프로젝트 경험 재분석').click(); const data = await json(await refreshed);
  assert.equal(data.input_revision, revision); assert.equal(data.experiences[0].user_answer, null);
  await focus();
  assert.equal((await result.locator('.activity-recommendations').innerText()).includes('확인한 프로젝트 경험'), false);
  assert.equal(activityCalls, 1);
  await focus(); assert.equal(activityCalls, 1);
  // Confirm again, then fail the other tab's refresh. Previous evidence stays valid.
  await editor.bringToFront(); await button(editor, '맞아요').click(); await waitText(editor, '본인 경험으로 확인');
  await focus(); await waitText(result, '확인한 프로젝트 경험');
  const callsBeforeFailure = activityCalls;
  await json(await editor.request.post(origin + '/api/review-fixture', { headers: { Origin: origin }, data: { project_failure: true } }));
  await editor.bringToFront(); await button(editor, '프로젝트 경험 재분석').click();
  await waitText(editor, '재분석을 완료하지 못해 기존 분석 결과와 사용자 답변을 유지했습니다.');
  await focus(); assert.equal(activityCalls, callsBeforeFailure);
  assert.ok((await result.locator('.activity-recommendations').innerText()).includes('확인한 프로젝트 경험'));
  await json(await editor.request.post(origin + '/api/review-fixture', { headers: { Origin: origin }, data: { project_failure: false } }));
 });

 await scenario('clipped negative evidence stays unverified in comparison and saved roadmap', async context => {
  const { page, base } = await guest(context);
  await page.getByLabel('프로젝트 문서 선택').setInputFiles({ name: 'negative.txt', mimeType: 'text/plain', buffer: Buffer.from('제가 SQL을 사용하지 않았습니다.') });
  await waitText(page, '읽기 완료 · 분석 포함 가능');
  await page.goto(origin + '/input/review'); await button(page, '프로젝트 경험 분석 실행').click();
  await waitText(page, '수행 주체 미확인');
  const analysis = await json(await page.request.get(base + '/project-experience-analysis'));
  assert.equal(analysis.experiences[0].evidence_text, '제가 SQL을 사용');
  assert.equal(analysis.experiences[0].contribution_scope, 'unknown');
  assert.equal(analysis.experiences[0].user_answer, null);
  await page.goto(origin + '/result');
  await page.getByRole('tab', { name: '직무 역량 비교', exact: true }).click();
  await button(page, '직무 분석 실행').click(); await waitText(page, '경험 확인 필요');
  assert.equal(await page.locator('.job-skills .badge').getByText('확인된 경험', { exact: true }).count(), 0);
  await page.getByRole('tab', { name: '실행 로드맵', exact: true }).click();
  await button(page, '로드맵 생성').click(); await waitText(page, '작업 완료 0 / 3개');
  const saved = await json(await page.request.get(base + '/roadmap'));
  assert.deepEqual(saved.preparation_summary.confirmed_skills, []);
  assert.deepEqual(saved.preparation_summary.learning_candidates, []);
  assert.ok(saved.roadmap.every(step => step.tasks.every(task => task.task_type === 'verify_experience')));
  await page.reload(); await waitText(page, '생성 처리 완료 시각');
  assert.equal((await json(await page.request.get(base + '/roadmap'))).run_id, saved.run_id);
 });
 console.log(JSON.stringify(reports, null, 2));
 if (failures.length) throw new AggregateError(failures, 'Review regression failures');
} finally { await browser.close(); }

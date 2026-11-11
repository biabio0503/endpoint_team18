// Controlled browser regression; API responses are fixtures, never a production E2E claim.
// Run against `next start -p 3100`, built with the test public auth configuration.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE && { executablePath: process.env.CHROMIUM_EXECUTABLE }) });
const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
const id = '11111111-1111-1111-1111-111111111111', userId = 'fixture-user';
let mode = 'success', activityCalls = 0, roadmapFails = true;
const item = { id: 'fixture', kind: 'competition', title: '공공데이터 분석 경진대회', category: '데이터·통계',
 host: '테스트 기관', target: '대학생', period: '2026.11.01 ~ 2026.12.01', deadline_label: '2026-12-01 (한국 시간, 당일 포함)',
 reasons: ['진로 목표 “데이터 분석가”에 맞춰, 공고 제목 “공공데이터 분석 경진대회”의 데이터 표현을 근거로 추천합니다.'],
 url: 'https://www.contestkorea.com/sub/view.php?str_no=fixture' };
await context.addInitScript(({ id, userId }) => {
 localStorage.setItem('sb-team18-test-auth-token', JSON.stringify({ access_token: 'fixture-token', refresh_token: 'fixture-refresh',
  expires_at: Math.floor(Date.now()/1000) + 3600, token_type: 'bearer', user: { id: userId } }));
 sessionStorage.setItem('roadmap_request_id', id); sessionStorage.setItem('roadmap_request_owner', userId);
}, { id, userId });
await context.route('**/api/**', async route => {
 const path = new URL(route.request().url()).pathname;
 let body, status = 200;
 if (path.endsWith('/activities')) {
  activityCalls++;
  if (mode === 'network') { await route.abort(); return; }
  body = { status: mode === 'partial' ? 'partial' : mode === 'error' ? 'error' : 'success',
   request_id: id, input_revision: 1, career_goal: '데이터 분석가', evaluated_at: new Date().toISOString(),
   valid_until: new Date(Date.now()+300000).toISOString(), sample_notice: '브라우저 회귀 테스트용 고정 공고입니다.',
   activities: ['success','partial'].includes(mode) ? [item] : [], sources: [
    { kind: 'competition', status: mode === 'error' ? 'error' : 'success' },
    { kind: 'extracurricular', status: ['partial','error'].includes(mode) ? 'error' : 'success' }] };
 } else if (path.endsWith('/roadmap') || path.endsWith('/roadmaps')) {
  status = roadmapFails ? 503 : 200;
  body = roadmapFails ? { error: 'roadmap_failed', message: '로드맵 조회 테스트 실패' } : { runs: [], status: 'needs_job_analysis' };
 } else body = { request_id: id, input_revision: 1, input: { career_goal: '데이터 분석가' } };
 await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
});
await context.route('https://www.contestkorea.com/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>원문 링크 목적지 확인</h1>' }));
const page = await context.newPage();
const errors = []; page.on('pageerror', error => errors.push(error.message));
try {
 await page.goto(process.env.WEB_TEST_ORIGIN || 'http://localhost:3100/result');
 await page.getByRole('tab', { name: '준비 상태' }).focus();
 await page.keyboard.press('End');
 await page.getByRole('heading', { name: item.title }).waitFor();
 assert.equal(await page.getByRole('tab', { name: '공모전·대외활동' }).getAttribute('aria-selected'), 'true');
 assert.ok(await page.getByText(item.reasons[0]).isVisible());
 assert.match(await page.locator('.result-summary').innerText(), /데이터 분석가/);
 assert.match(await page.locator('.result-summary').innerText(), /입력 버전 1/);
 assert.ok(await page.getByText(item.deadline_label, { exact: true }).isVisible());
 // Roadmap HTTP 503 does not block this panel. Repeated tab visits do not recollect.
 await page.keyboard.press('Home');
 await page.keyboard.press('End');
 await page.getByRole('heading', { name: item.title }).waitFor();
 assert.equal(activityCalls, 1);
 const popupEvent = context.waitForEvent('page');
 await page.getByRole('link', { name: /원문 보기/ }).click();
 const popup = await popupEvent; await popup.waitForLoadState();
 assert.equal(popup.url(), item.url); await popup.close();
 mode = 'partial';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByText('대외활동: 공급자에서 공고를 가져오지 못했습니다.').waitFor();
 assert.ok(await page.getByRole('heading', { name: item.title }).isVisible());
 await page.setViewportSize({ width: 390, height: 844 });
 await page.screenshot({ path: process.env.WEB_TEST_SCREENSHOT || '/tmp/team18-activities-mobile.png', fullPage: true });
 assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
 mode = 'empty';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByText(/현재 추천 조건에 맞는 공고가 없습니다/).waitFor();
 assert.equal(await page.getByRole('heading', { name: item.title }).count(), 0);
 mode = 'error';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByRole('alert').filter({ hasText: '공모전·대외활동 공급자 조회에 실패' }).waitFor();
 assert.equal(await page.getByText(/현재 추천 조건에 맞는 공고가 없습니다/).count(), 0);
 mode = 'network';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByRole('alert').filter({ hasText: '서버에 연결할 수 없습니다' }).waitFor();
 roadmapFails = false;
 await page.getByRole('tab', { name: '준비 상태' }).click();
 await page.getByRole('button', { name: '로드맵 생성', exact: true }).waitFor();
 assert.equal(errors.length, 0, errors.join('\n'));
 console.log('Browser regression passed: goal-only, roadmap failure isolation, keyboard tabs, cache reuse, partial/empty/failure, original link, mobile layout.');
} finally { await browser.close(); }

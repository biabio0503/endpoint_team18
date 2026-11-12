// Controlled browser regression; API responses are fixtures, never a production E2E claim.
// Run against `next start -p 3100`, built with the test public auth configuration.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const storedResponse = process.env.ACTIVITY_REVIEW_API_ARTIFACT
 ? JSON.parse(readFileSync(process.env.ACTIVITY_REVIEW_API_ARTIFACT, 'utf8')) : null;
const closedResponse = process.env.ACTIVITY_REVIEW_CLOSED_ARTIFACT
 ? JSON.parse(readFileSync(process.env.ACTIVITY_REVIEW_CLOSED_ARTIFACT, 'utf8')) : null;
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE && { executablePath: process.env.CHROMIUM_EXECUTABLE }) });
const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
const id = '11111111-1111-1111-1111-111111111111', userId = 'fixture-user', activityBasis = 'fixture-basis';
let mode = 'success', activityCalls = 0, roadmapFails = true;
const item = storedResponse?.activities[0] || { id: 'fixture', kind: 'competition', status: 'open', source_label: '콘테스트코리아 · 데이커', title: '공공데이터 분석 경진대회', category: '데이터·통계',
 host: '테스트 기관', target: '대학생', period: '2026.11.01 ~ 2026.12.01', deadline_label: '2026-12-01 (한국 시간, 당일 포함)',
 reasons: ['진로 목표 “데이터 분석가”에 맞춰, 공고 제목 “공공데이터 분석 경진대회”의 데이터 표현을 근거로 추천합니다.'],
 url: 'https://www.contestkorea.com/sub/view.php?str_no=fixture', source_links: [
  { source: 'contestkorea', source_label: '콘테스트코리아', url: 'https://www.contestkorea.com/sub/view.php?str_no=fixture', last_success_at: '2026-11-10T09:10:00+09:00', stale: true },
  { source: 'daker', source_label: '데이커', url: 'https://daker.ai/public/hackathons/fixture', last_success_at: '2026-11-12T09:10:00+09:00', stale: false }
 ] };
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
  body = { ...storedResponse, status: mode === 'partial' ? 'partial' : mode === 'error' ? 'error' : 'success',
   request_id: id, input_revision: 1, activity_basis: activityBasis, career_goal: '데이터 분석가', evaluated_at: new Date().toISOString(),
   valid_until: new Date(Date.now()+300000).toISOString(), sample_notice: '브라우저 회귀 테스트용 고정 공고입니다.',
   activities: mode === 'upcoming' ? [{ ...item, status: 'upcoming', opens_at: '2026-12-01T09:00:00+09:00',
      period: '2026.12.01 09:00 ~ 2026.12.31', deadline_label: '2026-12-31 (한국 시간, 당일 포함)' }]
     : ['success','partial'].includes(mode) ? [item] : mode === 'empty' && closedResponse ? closedResponse.activities : [], sources: [
    { source: 'contestkorea', kind: 'competition', status: mode === 'error' ? 'error' : 'success' },
    { source: 'dacon_daker', kind: 'competition', status: ['partial','error'].includes(mode) ? 'error' : 'success' }] };
 } else if (path.endsWith('/roadmap') || path.endsWith('/roadmaps')) {
  status = roadmapFails ? 503 : 200;
  body = roadmapFails ? { error: 'roadmap_failed', message: '로드맵 조회 테스트 실패' } : { runs: [], status: 'needs_job_analysis' };
 } else body = { request_id: id, input_revision: 1, activity_basis: activityBasis, input: { career_goal: '데이터 분석가' } };
 await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
});
await context.route('https://www.contestkorea.com/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>원문 링크 목적지 확인</h1>' }));
await context.route('https://daker.ai/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>데이커 원문 링크 목적지 확인</h1>' }));
const page = await context.newPage();
const errors = []; page.on('pageerror', error => errors.push(error.message));
try {
 await page.goto(new URL('/result', process.env.WEB_TEST_ORIGIN || 'http://localhost:3100').href);
 await page.getByRole('tab', { name: '준비 상태' }).focus();
 await page.keyboard.press('End');
 await page.getByRole('heading', { name: item.title }).waitFor();
 assert.equal(await page.getByRole('tab', { name: '공모전·대외활동' }).getAttribute('aria-selected'), 'true');
 assert.ok(await page.getByText(item.reasons[0]).isVisible());
 assert.match(await page.locator('.result-summary').innerText(), /데이터 분석가/);
 assert.match(await page.locator('.result-summary').innerText(), /입력 버전 1/);
 assert.ok(await page.getByText(item.deadline_label, { exact: true }).isVisible());
 if (storedResponse) {
  assert.match(item.deadline_label, /10:00 마감/);
  assert.doesNotMatch(item.deadline_label, /당일 포함/);
  assert.equal(item.evidence[0].source, 'contestkorea');
  await page.screenshot({ path: process.env.WEB_TEST_EXACT_SCREENSHOT || '/tmp/team18-review-exact-deadline.png', fullPage: true });
 }
 // Roadmap HTTP 503 does not block this panel. Repeated tab visits do not recollect.
 await page.keyboard.press('Home');
 const planResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/roadmap-inputs/${id}`));
 await page.keyboard.press('End');
 await (await planResponse).finished();
 await page.locator('.activity-recommendations[aria-busy="false"]:visible').waitFor();
 await page.getByRole('heading', { name: item.title }).waitFor();
 assert.equal(activityCalls, 1);
 assert.equal(await page.getByRole('heading', { name: item.title }).count(), 1);
 assert.equal(await page.getByRole('link', { name: /원문 보기/ }).count(), 2);
 assert.ok(await page.getByText('콘테스트코리아 · 데이커', { exact: true }).isVisible());
 await page.getByText(/최근 재확인 지연/).first().waitFor();
 assert.equal(await page.getByText(/최근 재확인 지연/).count(), item.source_links.filter(link => link.stale).length);
 assert.equal(await page.getByRole('link', { name: /데이커 원문 보기/ }).getAttribute('href'), item.source_links[1].url);
 const popupEvent = context.waitForEvent('page');
 await page.getByRole('link', { name: /콘테스트코리아 원문 보기/ }).click();
 const popup = await popupEvent; await popup.waitForLoadState();
 assert.equal(popup.url(), item.url); await popup.close();
 const dakerPopupEvent = context.waitForEvent('page');
 await page.getByRole('link', { name: /데이커 원문 보기/ }).click();
 const dakerPopup = await dakerPopupEvent; await dakerPopup.waitForLoadState();
 assert.equal(dakerPopup.url(), item.source_links[1].url); await dakerPopup.close();
 mode = 'upcoming';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByText('접수 예정', { exact: true }).waitFor();
 assert.ok(await page.getByText('접수 시작', { exact: true }).isVisible());
 assert.match(await page.locator('.skill-summary').innerText(), /2026.*12.*01.*09:00/);
 await page.setViewportSize({ width: 390, height: 844 });
 assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
 await page.screenshot({ path: '/tmp/team18-activities-upcoming.png', fullPage: true });
 mode = 'partial';
 await page.getByRole('button', { name: '활동 추천 다시 확인' }).click();
 await page.getByText('데이콘·데이커: 공급자에서 공고를 가져오지 못했습니다.').waitFor();
 assert.ok(await page.getByText('접수 중', { exact: true }).isVisible());
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
} catch (error) {
 console.error('Browser state:', page.url(), (await page.locator('body').innerText()).slice(0, 3000), errors);
 await page.screenshot({ path: '/tmp/team18-activities-failure.png', fullPage: true });
 throw error;
} finally { await browser.close(); }

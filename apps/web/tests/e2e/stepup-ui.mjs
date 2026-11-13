// Run with the disposable guest_ui_server.py and Next configured for test Supabase.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.JOB_SKILLS_WEB_ORIGIN || 'http://localhost:15101';
const browser = await chromium.launch({ executablePath: process.env.P5_BROWSER, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const errors = [], authCalls = [];
const user = { id: '12345678-0000-4000-8000-000000000002', is_anonymous: true, aud: 'authenticated' };
await context.route('https://job-skills-test.supabase.co/**', async route => {
 authCalls.push(new URL(route.request().url()).pathname);
 await route.fulfill({ json: { access_token: 'test.token.value', refresh_token: 'test-refresh', expires_in: 3600, token_type: 'bearer', user } });
});
try {
 const page = await context.newPage();
 page.on('pageerror', e => errors.push(e.message));
 await page.goto(origin);
 await page.getByRole('button', { name: '로그인 없이 시작하기', exact: true }).click();
 await page.getByRole('button', { name: '작성하기', exact: true }).click();
 await page.getByRole('button', { name: '저장', exact: true }).click();
 assert.equal(await page.locator('[name=career_goal]').getAttribute('aria-invalid'), 'true');
 await page.locator('[name=career_goal]').fill('스텝업 대시보드 서버 복원 검증');
 page.once('dialog', dialog => dialog.dismiss());
 await page.getByRole('navigation', { name: '주 메뉴', exact: true }).getByRole('link', { name: '대시보드' }).click();
 assert.equal(new URL(page.url()).pathname, '/input/basic');
 assert.equal(await page.locator('[name=career_goal]').inputValue(), '스텝업 대시보드 서버 복원 검증');
 await page.getByRole('button', { name: '저장', exact: true }).click();
 await page.getByRole('status').filter({ hasText: '저장되었습니다.' }).waitFor();
 await page.getByRole('navigation', { name: '주 메뉴', exact: true }).getByRole('link', { name: '대시보드' }).click();
 await page.getByText('스텝업 대시보드 서버 복원 검증', { exact: true }).waitFor();
 await page.reload();
 await page.getByText('스텝업 대시보드 서버 복원 검증', { exact: true }).waitFor();
 const paths = ['/', '/dashboard', '/input/basic', '/input/documents', '/input/courses', '/input/review', '/result'];
 for (const width of [1440, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 });
  for (const path of paths) {
   await page.goto(origin + path);
   await page.waitForLoadState('networkidle');
   assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow ${width} ${path}`);
   assert.equal(await page.title(), '스텝업 | 나만의 진로 설계');
   if (path !== '/') assert.equal(await page.locator('.side-nav [aria-current=page]').count(), 1);
   if (width !== 320 && ['/', '/dashboard', '/input/basic'].includes(path)) await page.screenshot({ path: `/tmp/stepup-${path.replaceAll('/','')||'home'}-${width}.png`, fullPage: true });
  }
 }
 await page.goto(origin);
 await page.getByRole('button', { name: '이어서 작성', exact: true }).waitFor();
 page.once('dialog', dialog => dialog.accept());
 await page.getByRole('button', { name: '로그아웃', exact: true }).click();
 await page.getByRole('button', { name: 'Google로 계속하기', exact: true }).waitFor();
 assert.ok(authCalls.includes('/auth/v1/signup'), 'Anonymous login calls original auth provider');
 assert.ok(authCalls.includes('/auth/v1/logout'), 'Logout calls original auth provider');
 assert.equal(await page.evaluate(() => sessionStorage.getItem('roadmap_request_id')), null);
 // Verify Google still starts the provider OAuth redirect without signing into a real account.
 const oauth = page.waitForRequest(request => request.url().includes('/auth/v1/authorize?'));
 await page.getByRole('button', { name: 'Google로 계속하기', exact: true }).click();
 const request = new URL((await oauth).url());
 assert.equal(request.searchParams.get('provider'), 'google');
 assert.equal(request.searchParams.get('redirect_to'), origin + '/');
 assert.deepEqual(errors, []);
 console.log('PASS: Stepup guest login/logout, Google OAuth launch, server-backed dashboard reload, active navigation, all 7 pages at 1440/390/320px, no runtime errors');
} finally { await context.close(); await browser.close(); }

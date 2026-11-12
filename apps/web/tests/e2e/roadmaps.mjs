// UI-only test with fake auth and API responses; never contacts Gemini or a real DB.
// Start Next dev with NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co
// NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key, then run this script.
import { installRoadmapMock } from './roadmap.mock.mjs';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const origin = process.env.JOB_SKILLS_WEB_ORIGIN || 'http://localhost:15101';
const browser = process.env.P5_BROWSER || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const port = Number(process.env.ROADMAP_CDP_PORT || 9454);
const tmp = mkdtempSync(join(tmpdir(), 'job-skills-ui-'));
const child = spawn(browser, ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${tmp}`, 'about:blank'], { stdio: 'ignore' });
let ws;
try {
 let page;
 for (let i = 0; i < 80; i++) {
  try { page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(p => p.type === 'page'); if (page) break; } catch {}
  await delay(150);
 }
 assert.ok(page, 'Browser did not start');
 ws = new WebSocket(page.webSocketDebuggerUrl);
 await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
 let next = 0;
 const pending = new Map();
 ws.onmessage = event => {
  const data = JSON.parse(event.data);
  if (pending.has(data.id)) { const [resolve, reject] = pending.get(data.id); pending.delete(data.id); data.error ? reject(new Error(data.error.message)) : resolve(data.result); }
 };
 const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++next; pending.set(id, [resolve, reject]); ws.send(JSON.stringify({ id, method, params })); });
 const run = async expression => {
  const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
 };
 const wait = async expression => {
  for (let i = 0; i < 160; i++) { if (await run(expression)) return; await delay(100); }
  throw new Error(`Timed out: ${expression}\n${await run('document.body.innerText')}`);
 };
 const tab = async number => { await run(`document.getElementById('tab-${number}').click()`); };
 await send('Page.enable');

 await send('Page.addScriptToEvaluateOnNewDocument', { source: '(' + installRoadmapMock.toString() + ')()' });
 const click = text => run(`[...document.querySelectorAll('button')].find(e=>e.textContent===${JSON.stringify(text)}).click()`);
 await send('Page.navigate', { url: `${origin}/result` });
 await wait("document.body.innerText.includes('검증된 직무 분석이 없어 진로 목표·교육과정 기준의 수강 후보와 제한 안내')");
 assert.equal(await run('mockRoadmap.posts'), 0);
 await tab(4);
 await wait("document.body.innerText.includes('현재 추천 조건에 맞는 공고가 없습니다.')");
 assert.equal(await run("document.querySelectorAll('.activity-recommendations .skill-card').length"), 0);
 assert.equal(await run('mockRoadmap.posts'), 0);
 await tab(0);
 await run('mockRoadmap.jobAvailable=true');
 await click('로드맵 생성');
 await wait("document.body.innerText.includes('작업 완료 0 / 3개')");
 assert.equal(await run('mockRoadmap.posts'), 1);
 await wait("!!document.querySelector('input[type=checkbox]:not(:disabled)')");
 await run("document.querySelector('input[type=checkbox]').click()");
 await wait("document.body.innerText.includes('작업 완료 1 / 3개')");
 assert.equal(await run('mockRoadmap.revision'), 1);
 await send('Page.reload');
 await wait("document.body.innerText.includes('추가 학습을 검토할 기술')");
 assert.ok(await run("[...document.querySelectorAll('.skill-card')].find(e=>e.querySelector('h3')?.textContent.startsWith('CAD'))?.innerText.includes('생성 입력에 미포함 · 실제 제안 활동 0단계')"));
 assert.ok(await run("[...document.querySelectorAll('.skill-card')].find(e=>e.querySelector('h3')?.textContent.startsWith('SQL'))?.innerText.includes('로드맵 생성 입력에 포함 · 실제 제안 활동 3단계')"));
 await tab(2);
 await wait("document.body.innerText.includes('작업 완료 1 / 3개')");
 assert.equal(await run("document.querySelector('input[type=checkbox]').checked"), true);
 assert.equal(await run('mockRoadmap.posts'), 1);
 await click('로드맵 생성');
 await wait("document.body.innerText.includes('작업 완료 1 / 3개')");
 assert.equal(await run('mockRoadmap.posts'), 1);
 await tab(3);
 await wait("document.body.innerText.includes('TEST-DB')");
 assert.ok(await run("document.body.innerText.includes('수강 전 확인: Python') && document.body.innerText.includes('잠정 후보')"));
 assert.ok(await run("!document.body.innerText.includes('관련 학습 키워드:')"));
 await run("[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('공식 근거와 출처 쪽수')).click()");
 assert.ok(await run("document.body.innerText.includes('과목명 기반 추론') && document.body.innerText.includes('52쪽')"));
 await run("mockRoadmap.sql='not_verified';mockRoadmap.completed=true;mockRoadmap.revision++");
 await click('저장 결과 새로고침');
 await wait("document.body.innerText.includes('이전 입력·분석 기준')");
 await click('현재 입력으로 다시 분석');
 await wait("document.body.innerText.includes('SQL 경험 확인 1') && document.body.innerText.includes('작업 완료 0 / 3개')");
 await tab(3);
 await wait("document.body.innerText.includes('추천할 후보를 찾지 못했습니다')");
 assert.equal(await run('mockRoadmap.posts'), 2);
 await run('mockRoadmap.limited=true');
 await click('현재 입력으로 다시 분석');
 await wait("document.body.innerText.includes('Gemini 사용량 제한')");
 assert.equal(await run('mockRoadmap.runs.length'), 2);
 await run('mockRoadmap.limited=false;mockRoadmap.conflict=true');
 await click('현재 입력으로 다시 분석');
 await wait("document.body.innerText.includes('생성 중 입력이 변경되었습니다')");
 await tab(2);
 await run('mockRoadmap.progressConflict=true');
 await run("document.querySelector('input[type=checkbox]').click()");
 await wait("document.body.innerText.includes('다른 화면에서 진행 상태를 변경했습니다')");
 assert.equal(await run("document.querySelector('input[type=checkbox]').checked"), false);
 await run("(()=>{let e=document.querySelector('select[aria-label=\"결과 이력\"]');e.value='run-1';e.dispatchEvent(new Event('change',{bubbles:true}));})()");
 await wait("document.body.innerText.includes('SQL 학습 1') && document.body.innerText.includes('작업 완료 1 / 3개')");
 await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
 assert.ok(await run('document.documentElement.scrollWidth<=window.innerWidth'));
 const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
 writeFileSync('/tmp/team18-roadmap-ui.png', Buffer.from(screenshot.data, 'base64'));
 await run('mockRoadmap.removed=true;mockRoadmap.revision++');
 await click('저장 결과 새로고침');
 await wait("document.body.innerText.includes('상세 내용과 완료 체크 접근을 제한했습니다')");
 assert.equal(await run("document.querySelectorAll('input[type=checkbox]').length"), 0);
 assert.ok(!(await run("document.body.innerText.includes('SQL 학습 1')")));
 assert.equal(await run('mockRoadmap.posts'), 2);
 console.log('PASS: 5 tabs, explicit generation, persistence/reload, cache, progress/version conflict, personalization, course completion, stale history, 429/409 preservation, deleted-document restriction, mobile');
} finally {
 ws?.close(); child.kill(); await delay(500); rmSync(tmp, { recursive: true, force: true });
}

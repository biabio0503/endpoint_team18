// Real disposable API + 68-row catalog. No Gemini or production DB access.
// Start course_groups_ui_server.py and Next dev on :15101 with the test auth
// variables documented by the other browser tests, then run this script.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const origin = process.env.JOB_SKILLS_WEB_ORIGIN || 'http://localhost:15101';
const browser = process.env.P5_BROWSER || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const port = Number(process.env.COURSE_CDP_PORT || 9458);
const directory = mkdtempSync(join(tmpdir(), 'course-groups-ui-'));
const child = spawn(browser, ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${directory}`, 'about:blank'], { stdio: 'ignore' });
let ws;
try {
 const fixtureResponse = await fetch(origin + '/api/course-groups-qa');
 assert.equal(fixtureResponse.status, 200);
 const fixture = await fixtureResponse.json();
 const cookie = fixtureResponse.headers.get('set-cookie').split(';')[0];
 const separator = cookie.indexOf('=');
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
 const click = text => run(`[...document.querySelectorAll('button')].find(e=>e.textContent===${JSON.stringify(text)}&&!e.disabled).click()`);
 const search = async value => {
  await run(`(()=>{const e=document.querySelector('input[aria-label="과목명·코드 검색"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await wait(`document.querySelector('input[aria-label="과목명·코드 검색"]').value===${JSON.stringify(value)} && document.body.innerText.includes('검색 결과 1개') && !document.querySelector('[role=switch]').disabled`);
 };
 await send('Page.enable');
 await send('Network.setCookie', { name: cookie.slice(0, separator), value: cookie.slice(separator + 1), url: origin, httpOnly: true, sameSite: 'Lax' });
 await send('Page.addScriptToEvaluateOnNewDocument', { source: `
  localStorage.setItem('sb-job-skills-test-auth-token',JSON.stringify({access_token:'test.token.value',refresh_token:'test-refresh',expires_at:Math.floor(Date.now()/1000)+3600,expires_in:3600,token_type:'bearer',user:{id:'course-groups-qa-user',is_anonymous:true}}));
  sessionStorage.setItem('roadmap_request_id',${JSON.stringify(fixture.request_id)});
  sessionStorage.setItem('roadmap_request_owner','course-groups-qa-user');
 ` });
 await send('Page.navigate', { url: origin + '/input/courses' });
 await wait("document.body.innerText.includes('검색 결과 52개') && document.querySelectorAll('[role=switch]').length===20 && !document.querySelector('[role=switch]').disabled");
 assert.ok(await run("document.querySelector('aside').innerText.includes('2개 과목') && document.querySelector('aside').innerText.includes('자료구조 (Data Structure)') && document.querySelector('aside').innerText.includes('데이터베이스 (Database)')"));
 assert.equal(await run("document.querySelector('aside').querySelectorAll('strong')[1].textContent"), '6');
 const names = [];
 for (let pageNumber = 1; pageNumber <= 3; pageNumber++) {
  await wait(`document.querySelector('.pagination').innerText.includes('${pageNumber} / 3') && !document.querySelector('[role=switch]').disabled`);
  names.push(...await run("[...document.querySelectorAll('tbody td strong')].map(e=>e.textContent)"));
  if (pageNumber < 3) await click('다음 페이지');
 }
 assert.equal(names.length, 52);
 assert.equal(new Set(names).size, 52);
 for (const query of ['데이터베이스', 'Database', 'database']) {
  await search(query);
  assert.equal(await run("document.querySelectorAll('[role=switch]').length"), 1);
  assert.equal(await run("document.querySelector('tbody strong').textContent"), '데이터베이스 (Database)');
  assert.equal(await run("document.querySelector('[role=switch]').getAttribute('aria-checked')"), 'true');
 }
 await run("document.querySelector('[role=switch]').click()");
 await wait("document.querySelector('[role=switch]').getAttribute('aria-checked')==='false' && !document.querySelector('[role=switch]').disabled");
 await send('Page.reload');
 await wait("document.body.innerText.includes('검색 결과 52개') && !document.querySelector('[role=switch]').disabled");
 await search('database');
 assert.equal(await run("document.querySelector('[role=switch]').getAttribute('aria-checked')"), 'false');
 assert.ok(await run("document.querySelector('aside').innerText.includes('1개 과목')"));
 let saved = await (await fetch(origin + '/api/course-groups-qa')).json();
 const dbIds = ['stcse-2026-ac66832f2c533c700dde1354', 'stcse-2026-56e5e2a1aedbfd4d2e87404c'];
 assert.ok(saved.states.filter(s => dbIds.includes(s.course_id)).every(s => !s.is_completed));
 await run("document.querySelector('[role=switch]').click()");
 await wait("document.querySelector('[role=switch]').getAttribute('aria-checked')==='true' && !document.querySelector('[role=switch]').disabled");
 saved = await (await fetch(origin + '/api/course-groups-qa')).json();
 assert.deepEqual(saved.states.filter(s => dbIds.includes(s.course_id) && s.is_completed).map(s => s.course_id), [dbIds[0]]);
 await send('Page.navigate', { url: origin + '/input/review' });
 await wait("document.querySelector('[aria-label=\"이수 과목 확인\"]').innerText.includes('2개 과목')");
 assert.ok(await run("document.querySelector('[aria-label=\"이수 과목 확인\"]').innerText.includes('자료구조 (Data Structure)') && document.querySelector('[aria-label=\"이수 과목 확인\"]').innerText.includes('데이터베이스 (Database)')"));
 assert.equal(await run("document.querySelector('[aria-label=\"이수 과목 확인\"]').querySelectorAll('strong')[1].textContent"), '6');
 await send('Page.navigate', { url: origin + '/result' });
 await wait("document.getElementById('tab-3') && document.body.innerText.includes('이 결과는 이전')");
 await run("document.getElementById('tab-3').click()");
 await wait("document.body.innerText.includes('수강 후보') && document.querySelectorAll('.skill-card').length===1");
 assert.ok(await run("document.querySelector('.skill-card h3').textContent.startsWith('데이터베이스 (Database)')"));
 await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
 assert.ok(await run('document.documentElement.scrollWidth<=window.innerWidth'));
 const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
 writeFileSync('/tmp/team18-course-groups-ui.png', Buffer.from(screenshot.data, 'base64'));
 await run("document.getElementById('tab-2').click()");
 await wait("document.body.innerText.includes('관련 수강 후보: 데이터베이스 (Database)')");
 const related = await run("[...document.querySelectorAll('.skill-card > p')].map(e=>e.textContent).filter(t=>t.startsWith('관련 수강 후보:'))");
 assert.deepEqual(related, Array(3).fill('관련 수강 후보: 데이터베이스 (Database)'));
 assert.equal((await (await fetch(origin + '/api/course-groups-qa')).json()).ai_calls, 0);
 console.log('PASS: 52 unique rows, bilingual/case-insensitive search, legacy 2 courses/6 credits, one-toggle clear/reload, canonical reselection, review summary, one historical card, both step aliases, no AI, mobile layout');
} finally {
 ws?.close(); child.kill(); await delay(500); rmSync(directory, { recursive: true, force: true });
}

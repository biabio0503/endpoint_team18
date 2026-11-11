// Local real API/SQLite/worker E2E. Only browser Auth session is synthetic.
// Run apps/api/tests/integration/guest_ui_server.py and Next on localhost:15101.
// Start Next dev with NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co
// NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key, then run this script.

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const origin = process.env.JOB_SKILLS_WEB_ORIGIN || 'http://localhost:15101';
const browser = process.env.P5_BROWSER || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const port = Number(process.env.GUEST_CDP_PORT || 9457);
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
  for (let i = 0; i < 160; i++) { if (await run(`(async()=>Boolean(await (${expression})))()`)) return; await delay(100); }
  throw new Error(`Timed out: ${expression}\n${await run('document.body.innerText')}`);
 };
 const tab = async number => { await run(`document.getElementById('tab-${number}').click()`); };
 await send('Page.enable');

 await send('Page.addScriptToEvaluateOnNewDocument',{source:`
  localStorage.setItem('sb-job-skills-test-auth-token',JSON.stringify({access_token:'test.token.value',refresh_token:'test-refresh',expires_at:Math.floor(Date.now()/1000)+3600,expires_in:3600,token_type:'bearer',user:{id:'guest-ui-user',is_anonymous:true}}));
  window.auditRequests=[];const nativeFetch=window.fetch;
  window.fetch=(input,options={})=>{window.auditRequests.push({url:String(input),method:options.method||'GET'});return nativeFetch(input,options)};
 `});
 const click=text=>run(`[...document.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(text)}&&!b.disabled).click()`);
 const set=async(selector,value)=>{
  await run(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e),'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
 };
 await send('Page.navigate',{url:origin+'/'});
 await wait("[...document.querySelectorAll('button')].some(b=>b.textContent==='작성하기'&&!b.disabled)");
 assert.equal(await run("[...document.querySelectorAll('a')].some(a=>a.textContent==='저장 결과·분석 단계로 이동')"),false);
 await click('작성하기');
 await wait("document.querySelector('textarea[name=career_goal]')");
 await set('textarea[name=career_goal]','데이터 분석 업무를 준비하는 격리 검수');
 await set('select[name=university_id]','10000000-0000-4000-8000-000000000001');
 await wait("!document.querySelector('select[name=department_id]').disabled");
 await set('select[name=department_id]','20000000-0000-4000-8000-000000000001');
 await wait("!document.querySelector('select[name=catalog_id]').disabled");
 await set('select[name=catalog_id]','30000000-0000-4000-8000-000000000001');
 await click('저장 후 다음: 프로젝트 문서');
 await wait("location.pathname==='/input/documents'");
 const rid=await run("sessionStorage.getItem('roadmap_request_id')");
 const upload=await run(`(async()=>{const plan=await(await fetch('/api/roadmap-inputs/${rid}')).json();const f=new FormData();f.set('expected_input_revision',String(plan.input_revision));f.set('file',new File(['제가 Python으로 테스트 데이터를 정리했습니다.'],'isolated-audit.txt',{type:'text/plain'}));const r=await fetch('/api/roadmap-inputs/${rid}/documents',{method:'POST',body:f});return {status:r.status,data:await r.json()}})()`);
 assert.equal(upload.status,201);
 await wait(`(async()=>{const r=await(await fetch('/api/roadmap-inputs/${rid}/documents')).json();return r.documents.some(d=>d.extraction_status==='ready')})()`);
 await send('Page.navigate',{url:origin+'/input/courses'});
 await wait("document.querySelectorAll('tbody tr').length===20");
 assert.equal(await run("document.querySelector('select[aria-label=\"페이지당 과목 수\"]').value"),'20');
 await set('select[aria-label="페이지당 과목 수"]','10');
 await wait("document.querySelectorAll('tbody tr').length===10");
 await click('다음 페이지');
 await wait("document.querySelector('.pagination').innerText.includes('2 / 4') && document.querySelector('tbody').innerText.includes('AUDIT10') && !document.querySelector('button[role=switch]').disabled");
 await run("document.querySelector('button[role=switch]').click()");
 await wait("document.querySelector('button[role=switch][aria-checked=true]')");
 await set('input[aria-label="과목명·코드 검색"]','검색결과없음');
 await wait("document.querySelector('tbody').innerText.includes('검색 결과가 없습니다')");
 assert.ok(await run("document.body.innerText.includes('전체 선택 1개')"));
 await click('검색·필터 초기화');
 await wait("document.querySelectorAll('tbody tr').length===10");
 await set('input[aria-label="과목명·코드 검색"]','AUDIT');
 await wait("document.body.innerText.includes('검색 결과 30개')");
 await click('이수 선택 확인 완료');
 await wait("document.body.innerText.includes('현재 목록 전체의 확인 상태가 저장되었습니다')");
 await send('Page.reload');
 await wait("document.body.innerText.includes('이수 선택 확인 완료') && document.body.innerText.includes('전체 선택 1개')");
 await click('다음: 분석 내용 확인');
 await wait("location.pathname==='/input/review'");
 await send('Page.navigate',{url:origin+'/result'});
 await wait("[...document.querySelectorAll('button')].some(b=>b.textContent==='제한 안내 로드맵 생성'&&!b.disabled)");
 await click('제한 안내 로드맵 생성');
 await wait("document.body.innerText.includes('작업 완료 0 / 3개')");
 await run("document.querySelector('input[type=checkbox]').click()");
 await wait("document.body.innerText.includes('작업 완료 1 / 3개')");
 await send('Page.reload');
 await wait("document.body.innerText.includes('생성 처리 완료 시각') && document.querySelectorAll('[role=tab]').length===5");
 await tab(2); await wait("document.body.innerText.includes('작업 완료 1 / 3개')");
 await tab(1); await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='false'");
 assert.equal(await run("auditRequests.filter(r=>r.method==='POST'&&/job-skill-analysis|project-experience-analysis/.test(r.url)).length"),0);
 await tab(3); await wait("document.body.innerText.includes('수강 후보 추천을 보류')");
 await tab(4); await wait("document.querySelector('.activity-recommendations')?.getAttribute('aria-busy')==='false' && document.body.innerText.includes('공급자 연결이 아직 설정되지 않았습니다.')");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.ok(await run('document.documentElement.scrollWidth<=window.innerWidth'));
 const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
 writeFileSync('/tmp/team18-guest-flow.png',Buffer.from(screenshot.data,'base64'));
 await send('Page.navigate',{url:origin+'/'});
 await wait("[...document.querySelectorAll('button')].some(b=>b.textContent==='이어서 작성'&&!b.disabled)");
 await click('이어서 작성');
 await wait("document.querySelector('textarea[name=career_goal]')?.value==='데이터 분석 업무를 준비하는 격리 검수'");
 console.log('PASS: real local API plan/create/resume, basic restore, document upload/extract, 20/10 page size, search/reset/selection/review restore, limited roadmap persistence/checks, 5 tabs, no automatic AI, mobile');
} finally {
 ws?.close(); child.kill(); await delay(500); rmSync(tmp,{recursive:true,force:true});
}

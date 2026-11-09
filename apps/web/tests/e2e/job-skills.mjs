// UI-only test with fake auth and API responses; never contacts Gemini or a real DB.
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
const port = Number(process.env.JOB_SKILLS_CDP_PORT || 9452);
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
 await send('Page.addScriptToEvaluateOnNewDocument', { source: `
  localStorage.setItem('sb-job-skills-test-auth-token', JSON.stringify({access_token:'test.token.value', refresh_token:'test-refresh', expires_at:Math.floor(Date.now()/1000)+3600, expires_in:3600, token_type:'bearer', user:{id:'test-user'}}));
  sessionStorage.setItem('roadmap_request_id','test-plan');
  sessionStorage.setItem('roadmap_request_owner','test-user');
  window.mockAnalysis={revision:1,posts:0,courses:0,status:'success'};
  const nativeFetch=window.fetch;
  window.fetch=async (input,options={})=>{
   const url=String(input);
   if (!url.includes('/api/')) return nativeFetch(input,options);
   const m=window.mockAnalysis;
   const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
   if(url.endsWith('/course-recommendations')) {m.courses++;return json({career_goal:'보안 개발',input_revision:m.revision,courses:[{course_id:'course-1',course_name:'기존 수강 추천'}],status:'ok'});}
   if(url.endsWith('/skill-comparison')) return json({input_revision:m.revision,job_analysis:m.saved||{status:'not_started',skills:[]}});
   if(!url.endsWith('/job-skill-analysis')) return json({input_revision:m.revision});
   m.posts++;
   await new Promise(resolve=>setTimeout(resolve,250));
   if(m.status==='conflict') return json({error:'revision_conflict',message:'분석 중 입력이 변경되었습니다. 다시 시도해 주세요.'},409);
   const skill={name:'Python',category:'programming_language',mentioned_job_count:1,mention_frequency:1,required_job_count:1,preferred_job_count:0,mentioned_only_job_count:0,unknown_job_count:0,direct_job_count:1,related_job_count:0,seniority_distribution:{entry:1,mid:0,senior:0,unknown:0},evidence:[{job_id:'job-1',title:'Security Engineer',source_url:'https://himalayas.app/companies/example/jobs/security',requirement_type:'required',evidence_text:'Python is required.'}]};
   skill.priority_reason='직무 업무·요건 근거 1개 독립 공고; 필수 1, 우대 0.';
   skill.single_job_notice='1개 독립 공고에서만 확인했습니다.';
   return json(m.saved={analysis_version:'job-skills-v2',sample_notice:'조건을 통과한 공고는 1개입니다. 작은 해외 원격근무 표본입니다.',snapshot_id:'job-snapshot',status:m.status,career_goal:'보안 개발',target_role:'보안 엔지니어',canonical_role:'Security Engineer',input_revision:m.revision,keyword_details:[{keyword:'Security Engineer',relation:'direct'}],collection_summary:{selected_jobs:1},analysis_summary:{analyzed_jobs:1,failed_jobs:m.status==='partial'?1:0,skipped_jobs:0},skills:['success','partial'].includes(m.status)?[skill]:[],retrieved_at:'2026-11-09T04:00:00Z',clarification_message:'관심 업무를 구체화해 주세요.',errors:m.status==='error'?[{message:'Gemini 요청 시간이 초과되었습니다.'}]:[]});
  };
 ` });
 await send('Page.navigate', { url: `${origin}/result` });
 await wait("document.querySelectorAll('[role=tab]').length===5");
 await delay(800);
 assert.equal(await run('window.mockAnalysis.posts'), 0);
 await tab(1);
 await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='false'");
 assert.equal(await run('window.mockAnalysis.posts'),0);
 await run("[...document.querySelectorAll('button')].find(b=>b.textContent==='직무 분석 실행').click()");
 await wait("document.querySelector('.skill-card')?.innerText.includes('Python')");
 assert.equal(await run('window.mockAnalysis.posts'), 1);
 assert.ok(await run("document.body.innerText.includes('1개 독립 공고에서만 확인') && document.body.innerText.includes('작은 해외 원격근무 표본')"));
 await run("document.querySelector('.skill-card summary').click()");
 assert.equal(await run("document.querySelector('.skill-evidence a').hostname"), 'himalayas.app');
 assert.ok(await run("document.querySelector('.skill-evidence').innerText.includes('Python is required.')"));
 await tab(3);
 await wait("document.getElementById('result-panel').innerText.includes('로드맵 생성')");
 // The result screen now has one recommendation source; the legacy API remains independent.
 const legacy = await run("fetch('/api/roadmap-inputs/test-plan/course-recommendations',{method:'POST',body:'{}'}).then(r=>r.json())");
 assert.equal(legacy.courses[0].course_name, '기존 수강 추천');
 await tab(1);
 await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='false'");
 assert.equal(await run('window.mockAnalysis.posts'), 1);
 assert.equal(await run('window.mockAnalysis.courses'), 1);
 const change = async status => {
  await tab(0);
  await run(`window.mockAnalysis.revision++;window.mockAnalysis.status=${JSON.stringify(status)}`);
  await tab(1);
  await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='false'");
  await run("[...document.querySelectorAll('button')].find(b=>b.textContent==='직무 분석 다시 실행').click()");
  await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='true'");
  await wait("document.querySelector('.job-skills').getAttribute('aria-busy')==='false'");
 };
 await change('partial');
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('확인된 결과만')"));
 assert.equal(await run('window.mockAnalysis.posts'), 2);
 await change('no_jobs');
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('관련 공고가 없습니다')"));
 await change('needs_clarification');
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('관심 업무를 구체화')"));
 await change('error');
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('시간이 초과')"));
 await change('conflict');
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('입력이 변경')"));
 assert.ok(await run("document.querySelector('.job-skills').innerText.includes('입력이 변경')"));
 await change('success');
 await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
 assert.ok(await run('document.documentElement.scrollWidth<=window.innerWidth'));
 const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
 writeFileSync('/tmp/team18-job-skills-ui.png', Buffer.from(screenshot.data, 'base64'));
 console.log('PASS: lazy analysis, cache, revision invalidation, source evidence, partial/error/no-jobs/clarification/409, course recommendation, mobile layout');
} finally {
 ws?.close();
 child.kill();
 await delay(500);
 rmSync(tmp, { recursive: true, force: true });
}

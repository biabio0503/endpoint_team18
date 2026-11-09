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
const port = Number(process.env.PROJECT_CDP_PORT || 9453);
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
  const m=window.mockProject={revision:1, projectCalls:0, jobCalls:0, analyzed:false, answers:{}, skillAnswer:null, removed:false};
  const item=(name,scope)=>({experience_id:name,analysis_id:'a1',skill_name:name,activity:name+' 작업',contribution_scope:scope,document_id:'doc1',extraction_revision:1,evidence_start:0,evidence_end:22,locations:[{paragraph:1}],original_filename:'프로젝트.txt',evidence_text:'제가 Python으로 전처리했습니다.',user_confirmation:m.answers[name]?.status||null,user_answer:m.answers[name]||null});
  const project=()=>({status:m.removed?'no_documents':m.analyzed?'success':'not_started',input_revision:m.revision,eligible_documents:m.removed?0:1,analyzed_documents:m.analyzed&&!m.removed?1:0,verified_experiences:m.analyzed&&!m.removed?2:0,documents:[{document_id:'doc1',limitations:[]}],excluded_documents:[],errors:[],experiences:m.analyzed&&!m.removed?[item('Python','personal'),item('Docker','team')]:[]});
  const skill=name=>({name,category:'programming_language',mentioned_job_count:1,mention_frequency:1,required_job_count:1,preferred_job_count:0,mentioned_only_job_count:0,unknown_job_count:0,direct_job_count:1,related_job_count:0,seniority_distribution:{entry:1,mid:0,senior:0,unknown:0},evidence:[{job_id:'job1',title:'Data Analyst',source_url:'https://himalayas.app/companies/example/jobs/data',requirement_type:'required',evidence_text:name+' is required.'}]});
  const jobs=()=>({status:'success',career_goal:'데이터 분석 분야',canonical_role:'Data Analyst',target_role:'데이터 분석가',input_revision:m.revision,analyzed_input_revision:1,snapshot_id:'job-snapshot',reused:!!m.jobCalls,keyword_details:[],collection_summary:{selected_jobs:1},analysis_summary:{analyzed_jobs:1,failed_jobs:0,skipped_jobs:0},skills:[skill('Python'),skill('SQL'),skill('Docker')],errors:[]});
  const compare=()=>({status:'success',input_revision:m.revision,project_analysis:project(),job_analysis:jobs(),comparisons:jobs().skills.map(s=>{
   const evidence=project().experiences.filter(e=>e.skill_name===s.name);const a=evidence[0]?.user_answer;
   const status=s.name==='SQL'&&m.skillAnswer ? m.skillAnswer==='no_experience'?'no_experience':'needs_confirmation' : !evidence.length?'not_verified':a?.status==='confirmed'||a?.status==='corrected'?'confirmed_experience':a?.status==='unknown'?'needs_confirmation':s.name==='Python'?'document_supported':'needs_confirmation';
   return {skill_name:s.name,student_status:status,reason:status==='not_verified'?'현재 자료에서 수행 근거를 찾지 못했습니다. 경험이 없다는 뜻은 아닙니다.':'사용자 확인 상태',preparation_candidate:status==='no_experience'?'consider_learning':status==='confirmed_experience'?'experience_confirmed':'verify_experience_first',project_evidence:evidence,job_evidence:s.evidence};
  })});
  const nativeFetch=window.fetch;
  window.fetch=async(input,options={})=>{
   const url=String(input);if(!url.includes('/api/'))return nativeFetch(input,options);
   const json=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
   const body=options.body?JSON.parse(options.body):{};
   if(url.endsWith('/project-experience-analysis')){if(options.method==='POST'){if(!m.analyzed)m.projectCalls++;m.analyzed=true;}return json(project());}
   if(url.includes('/project-experiences/')&&url.endsWith('/confirmation')){const name=url.split('/').at(-2);m.answers[name]={status:body.status,correction:body.correction||null};m.revision++;return json(project());}
   if(url.endsWith('/skill-comparison/answers')){m.skillAnswer=body.status;m.revision++;return json(compare());}
   if(url.endsWith('/skill-comparison'))return json(compare());
   if(url.includes('/extractions/'))return json({is_current_revision:!m.removed,extracted_text:'제가 Python으로 전처리했습니다.'});
   if(url.endsWith('/job-skill-analysis')){if(!m.jobCalls)m.jobCalls++;return json(jobs());}
   return json({input_revision:m.revision});
  };
 ` });
 const clickText = async text => run(`[...document.querySelectorAll('button,a')].find(e=>e.textContent===${JSON.stringify(text)}).click()`);
 const card = name => `[...document.querySelectorAll('.skill-card')].find(e=>e.querySelector('h3').textContent===${JSON.stringify(name)})`;
 const cardClick = async (name, text) => run(`[...(${card(name)}).querySelectorAll('button')].find(e=>e.textContent===${JSON.stringify(text)}).click()`);
 await send('Page.navigate', { url: `${origin}/input/review` });
 await wait("document.body.innerText.includes('프로젝트 경험 분석 및 확인') && document.querySelector('section[aria-busy]').getAttribute('aria-busy')==='false'");
 assert.equal(await run('window.mockProject.projectCalls'), 0);
 assert.ok(await run("document.body.innerText.includes('외부 Gemini')"));
 await clickText('프로젝트 경험 분석 실행');
 await wait("document.querySelectorAll('.skill-card').length===2");
 await run(`(${card('Python')}).querySelector('summary').click()`);
 await cardClick('Python', '현재 문서 본문 확인');
 await wait("document.querySelectorAll('.source-text').length>=2");
 await cardClick('Python', '맞아요');
 await wait(`(${card('Python')}).innerText.includes('본인 경험으로 확인')`);
 await cardClick('Docker', '잘 모르겠어요');
 await wait(`(${card('Docker')}).innerText.includes('판단 보류')`);
 await cardClick('Docker', '수정할게요');
 await run(`(()=>{const form=(${card('Docker')}).querySelector('form');const area=form.querySelector('textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(area,'컨테이너를 직접 구성했습니다');area.dispatchEvent(new Event('input',{bubbles:true}));const select=form.querySelector('select');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,'personal');select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await cardClick('Docker', '수정 내용 저장');
 await wait(`(${card('Docker')}).innerText.includes('사용자가 수정')`);
 assert.equal(await run('window.mockProject.answers.Docker.correction.activity'), '컨테이너를 직접 구성했습니다');
 await clickText('프로젝트 경험 분석 실행');
 await wait("document.querySelector('section[aria-busy]').getAttribute('aria-busy')==='false'");
 assert.equal(await run('window.mockProject.projectCalls'), 1);
 await clickText('다음: 결과 화면에서 직무 분석·로드맵 생성 →');
 await wait("document.querySelectorAll('[role=tab]').length===5");
 await tab(1);
 await wait(`(${card('Python')})?.innerText.includes('확인된 경험')`);
 assert.ok(await run(`(${card('SQL')}).innerText.includes('자료에서 확인되지 않음')`));
 assert.ok(await run(`(${card('SQL')}).innerText.includes('경험이 없다는 뜻은 아닙니다')`));
 await run(`(${card('Python')}).querySelector('.project-evidence summary').click()`);
 assert.ok(await run(`(${card('Python')}).innerText.includes('제가 Python으로 전처리했습니다.')`));
 assert.equal(await run(`(${card('Python')}).querySelector('.skill-evidence a').hostname`), 'himalayas.app');
 await cardClick('SQL', '이 기술 경험 없어요');
 await wait(`(${card('SQL')})?.innerText.includes('추가 학습을 검토할 후보')`);
 await cardClick('SQL', '잘 모르겠어요');
 await wait(`(${card('SQL')})?.innerText.includes('경험 확인 필요')`);
 assert.equal(await run('window.mockProject.projectCalls'), 1);
 assert.equal(await run('window.mockProject.jobCalls'), 0);
 await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
 assert.ok(await run('document.documentElement.scrollWidth<=window.innerWidth'));
 const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
 writeFileSync('/tmp/team18-project-comparison-ui.png', Buffer.from(screenshot.data, 'base64'));
 await tab(0);
 await run('window.mockProject.removed=true;window.mockProject.revision++');
 await tab(1);
 await wait(`(${card('Python')})?.innerText.includes('자료에서 확인되지 않음')`);
 assert.equal(await run("document.querySelectorAll('.project-evidence').length"), 0);
 console.log('PASS: explicit consent, review, confirm/correct/defer, source text, experience comparison, no-experience distinction, reuse, invalidation, mobile');
} finally {
 ws?.close(); child.kill(); await delay(500); rmSync(tmp, { recursive: true, force: true });
}

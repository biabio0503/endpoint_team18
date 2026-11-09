// Run against isolated P5 API/web processes; no additional browser-test dependency.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const origin=process.env.P5_WEB_ORIGIN || 'http://localhost:15100';
const browserPath=process.env.P5_BROWSER || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const port=Number(process.env.P5_CDP_PORT || 9451);
const tmp=mkdtempSync(join(tmpdir(),'roadmap-p5-'));
writeFileSync(join(tmp,'project.txt'),'실제 검수 프로젝트: 데이터를 정리하고 결과를 기록했습니다.','utf8');
writeFileSync(join(tmp,'invalid.pdf'),'not a pdf','utf8');
const processBrowser=spawn(browserPath,['--headless=new','--no-sandbox','--disable-gpu',`--remote-debugging-port=${port}`,`--user-data-dir=${tmp}/profile`,'about:blank'],{stdio:'ignore'});
class CDP {
 constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&this.pending.has(m.id)){const [resolve,reject]=this.pending.get(m.id);this.pending.delete(m.id);m.error?reject(Error(m.error.message)):resolve(m.result)}}}
 static async open(url){const ws=new WebSocket(url);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});return new CDP(ws)}
 send(method,params={}){return new Promise((resolve,reject)=>{const id=++this.next;this.pending.set(id,[resolve,reject]);this.ws.send(JSON.stringify({id,method,params}))})}
 async run(expression){const r=await this.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
 async wait(expr){for(let i=0;i<160;i++){if(await this.run(expr))return;await delay(150)}throw Error(`timeout ${expr}: ${await this.run('document.body.innerText')}`)}
 async click(text){await this.run(`[...document.querySelectorAll('button,a')].find(x=>x.textContent.trim()===${JSON.stringify(text)})?.click()`)}
 async input(selector,value){await this.run(`(()=>{let e=document.querySelector(${JSON.stringify(selector)});const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}))})()`)}
 async select(name,value){await this.run(`(()=>{let e=document.querySelector('[name="${name}"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('change',{bubbles:true}))})()`)}
 async go(path){await this.send('Page.navigate',{url:origin+path});await delay(300)}
 async upload(path){await this.send('DOM.enable');const doc=await this.send('DOM.getDocument');const field=await this.send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'input[type=file]'});await this.send('DOM.setFileInputFiles',{nodeId:field.nodeId,files:[path]})}
 close(){this.ws.close()}
}
const pages=[];let control;
try{
 let version;for(let i=0;i<80;i++){try{version=await(await fetch(`http://127.0.0.1:${port}/json/version`)).json();break}catch{await delay(200)}}if(!version)throw Error('브라우저 디버깅 포트를 열지 못했습니다.');
 control=await CDP.open(version.webSocketDebuggerUrl);
 async function page(context){const target=await control.send('Target.createTarget',{url:'about:blank',...(context?{browserContextId:context}:{})});const list=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();const entry=list.find(x=>x.id===target.targetId);const p=await CDP.open(entry.webSocketDebuggerUrl);pages.push(p);await p.send('Page.enable');await p.go('/');await p.wait("document.body.innerText.includes('새 계획 시작')");await delay(1200);return p}
 const a=await page();
 await a.click('새 계획 시작');await a.wait("!!document.querySelector('[name=career_goal]')");
 if(await a.run("[...document.querySelectorAll('nav[aria-label=\"입력 단계\"] a')].some(x=>x.textContent.includes('이수 과목'))"))throw Error('입력 단계에서 과목 화면으로 건너뛸 수 있습니다.');
 await a.input('[name=career_goal]','데이터 분석을 준비합니다');await a.input('[name=target_role]','분석가');
 await a.select('university_id','10000000-0000-4000-8000-000000000001');await a.select('department_id','20000000-0000-4000-8000-000000000001');await a.select('catalog_id','30000000-0000-4000-8000-000000000001');await a.select('year_level','2');
 await a.run("document.querySelector('details').open=true");await a.input('[name=gpa]','4.8');await a.select('gpa_scale','4.5');await a.click('저장');await a.wait("document.body.innerText.includes('GPA는 0 이상 만점 이하')");await a.input('[name=gpa]','0');await a.input('[name=earned_credits]','0');
 await a.run("window.savedFetch=window.fetch;window.fetch=()=>Promise.reject(new Error('simulated offline'))");await a.click('저장');await a.wait("document.body.innerText.includes('서버에 연결할 수 없습니다')");await a.run('window.fetch=window.savedFetch');await a.click('저장');await a.wait("document.body.innerText.includes('저장되었습니다.')");
 const rid=await a.run("sessionStorage.getItem('roadmap_request_id')");if(!rid)throw Error('계획 ID가 없습니다.');
 await a.click('저장 후 다음: 프로젝트 문서');await a.wait("!!document.querySelector('input[type=file]')");await a.wait("[...document.querySelectorAll('button')].some(x=>x.textContent.includes('다음: 이수 과목')&&x.disabled)");
 await a.upload(join(tmp,'invalid.pdf'));await a.wait("document.body.innerText.includes('파일 내용이 PDF 형식이 아닙니다')");await a.click('최신 상태 불러오기');await a.wait("!!document.querySelector('input[type=file]:not(:disabled)')");
 await a.upload(join(tmp,'project.txt'));await a.wait("[...document.querySelectorAll('button')].some(x=>x.textContent==='읽힌 내용'&&!x.disabled)");await a.click('읽힌 내용');await a.wait("document.body.innerText.includes('실제 검수 프로젝트')");await a.click('닫기');await a.click('다음: 이수 과목');await a.wait("!!document.querySelector('[role=switch]')");
 await a.wait("[...document.querySelectorAll('button')].some(x=>x.textContent.includes('다음: 분석 내용 확인')&&x.disabled)");await a.click('이수 선택 확인 완료');await a.wait("document.body.innerText.includes('현재 목록 전체의 확인 상태가 저장되었습니다.')");
 await a.run("window.savedFetch=window.fetch;window.fetch=()=>Promise.reject(new Error('simulated offline'))");await a.run("document.querySelector('[role=switch]').click()");await a.wait("document.body.innerText.includes('저장 여부를 확인하려면 최신 상태를 불러와 주세요')");await a.run('window.fetch=window.savedFetch');await a.click('최신 상태 불러오기');await a.wait("document.body.innerText.includes('최신 선택 상태를 불러왔습니다.')");if(await a.run("document.querySelector('[role=switch]').getAttribute('aria-checked')!=='false'"))throw Error('실패한 과목 저장이 반영되었습니다.');
 await a.run("[...document.querySelectorAll('input[type=checkbox]')].find(x=>x.parentElement.innerText.includes('목록에 없는')).click()");
 await a.input('[aria-label="과목명·코드 검색"]','DEV201');await a.wait("document.querySelectorAll('tbody tr').length===1 && !!document.querySelector('[role=switch]:not(:disabled)')");
 if(!await a.run("[...document.querySelectorAll('input[type=checkbox]')].find(x=>x.parentElement.innerText.includes('목록에 없는')).checked"))throw Error('검색 중 미저장 누락 신고가 사라졌습니다.');
 await a.wait("[...document.querySelectorAll('button')].some(x=>x.textContent.includes('다음: 분석 내용 확인')&&x.disabled)");await a.click('이수 선택 확인 완료');await a.wait("document.body.innerText.includes('일부 누락 · 부분 확인')");
 await a.run("document.querySelector('[role=switch]').click()");await a.wait("!!document.querySelector('[role=switch][aria-checked=true]') && document.body.innerText.includes('이수 선택이 저장되었습니다.')");await a.run("[...document.querySelectorAll('input[type=checkbox]')].find(x=>x.parentElement.innerText.includes('목록에 없는')).click()");await a.click('이수 선택 확인 완료');await a.wait("document.body.innerText.includes('일부 누락 · 부분 확인') && document.body.innerText.includes('확인 상태가 저장되었습니다')");
 await a.input('[aria-label="과목명·코드 검색"]','');await a.wait("document.querySelectorAll('tbody tr').length===5 && !!document.querySelector('[role=switch]:not(:disabled)')");
 await a.run("(()=>{const e=document.querySelector('[aria-label=\"학년 필터\"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,'2');e.dispatchEvent(new Event('change',{bubbles:true}))})()");await a.wait("document.querySelectorAll('tbody tr').length===2 && !!document.querySelector('[role=switch]:not(:disabled)')");
 await a.run("[...document.querySelectorAll('input[type=checkbox]')].find(x=>x.parentElement.innerText.includes('선택한 과목만')).click()");await a.wait("document.querySelectorAll('tbody tr').length===1 && !!document.querySelector('[role=switch][aria-checked=true]:not(:disabled)')");
 await a.run("[...document.querySelectorAll('input[type=checkbox]')].find(x=>x.parentElement.innerText.includes('선택한 과목만')).click()");await a.wait("document.querySelectorAll('tbody tr').length===2 && !!document.querySelector('[role=switch]:not(:disabled)')");
 await a.run("(()=>{const e=document.querySelector('[aria-label=\"학년 필터\"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,'');e.dispatchEvent(new Event('change',{bubbles:true}))})()");await a.wait("document.querySelectorAll('tbody tr').length===5 && !!document.querySelector('[role=switch]:not(:disabled)')");await a.click('다음 페이지');await a.wait("document.body.innerText.includes('2 / 2') && !!document.querySelector('[role=switch]:not(:disabled)')");if(!await a.run("document.body.innerText.includes('1개 과목')"))throw Error('페이지 이동 중 선택이 사라졌습니다.');await a.click('이전 페이지');await a.wait("document.body.innerText.includes('1 / 2') && !!document.querySelector('[role=switch]:not(:disabled)')");
 await a.click('다음: 분석 내용 확인');await a.wait("document.body.innerText.includes('분석 기능을 준비 중입니다')");
 await a.run('history.back()');await a.wait("document.body.innerText.includes('일부 누락 · 부분 확인')");await a.send('Page.reload');await a.wait("document.body.innerText.includes('일부 누락 · 부분 확인') && !!document.querySelector('[role=switch][aria-checked=true]')");
 await a.go('/');await a.wait("document.body.innerText.includes('이어서 작성')");await delay(700);await a.click('이어서 작성');await a.wait("document.querySelector('[name=career_goal]')?.value==='데이터 분석을 준비합니다'");
 if(!await a.run("document.querySelector('[name=gpa]').value==='0' && document.querySelector('[name=earned_credits]').value==='0'"))throw Error('0 값이 복원되지 않았습니다.');
 const a2=await page();await a2.run(`sessionStorage.setItem('roadmap_request_id',${JSON.stringify(rid)})`);await a2.go('/input/basic');await a2.wait("document.querySelector('[name=career_goal]')?.value==='데이터 분석을 준비합니다'");
 await a2.input('[name=target_role]','다른 탭의 변경');await a2.click('저장');await a2.wait("document.body.innerText.includes('저장되었습니다.')");await a.input('[name=target_role]','오래된 탭의 변경');await a.click('저장');await a.wait("document.body.innerText.includes('다른 화면에서 입력이 변경')");await a.run('window.confirm=()=>true');await a.click('최신 내용 불러오기');await a.wait("document.querySelector('[name=target_role]')?.value==='다른 탭의 변경'");
 const context=(await control.send('Target.createBrowserContext')).browserContextId;const b=await page(context);
 const foreign=await b.run(`(async()=>{const a=await fetch('/api/roadmap-inputs/${rid}');return a.status})()`);if(foreign!==401)throw Error(`세션 없는 접근 ${foreign}`);
 await b.click('새 계획 시작');await b.wait("!!document.querySelector('[name=career_goal]')");
 const isolation=await b.run(`(async()=>{let root='/api/roadmap-inputs/${rid}';return Promise.all([fetch(root),fetch(root+'/documents'),fetch(root+'/courses?catalog_id=30000000-0000-4000-8000-000000000001'),fetch(root,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_input_revision:0,changes:{career_goal:'침입'}})})].map(async r=>(await r).status))})()`);
 if(isolation.some(x=>x!==404))throw Error('다른 세션 접근 차단 실패 '+JSON.stringify(isolation));
 await b.go('/input/courses');await b.wait("document.body.innerText.includes('현재 학교·학과의 과목 목록을 사용할 수 없습니다')");await b.click('수강 제안 없이 계속');await b.wait("document.body.innerText.includes('분석 기능을 준비 중입니다')");
 const fake=await a.run(`(async()=>{let r=await fetch('/api/roadmap-inputs/${rid}/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});return r.status})()`);if(fake!==404)throw Error('결과 생성 API가 예상과 다릅니다.');
 await a.go('/input/documents');await a.wait("document.body.innerText.includes('project.txt')");await a.go('/input/courses');await a.wait("document.body.innerText.includes('일부 누락 · 부분 확인') && !!document.querySelector('[role=switch][aria-checked=true]')");
 await a.go('/result');await a.wait("document.querySelectorAll('[role=tab]').length===5");for(let i=0;i<5;i++){await a.run(`document.querySelectorAll('[role=tab]')[${i}].click()`);const expected=i===1?'채용공고 기술 스택 분석':i===3?'수강 후보 분석':'아직 생성된 분석 결과가 없습니다';await a.wait(`document.querySelectorAll('[role=tab]')[${i}].getAttribute('aria-selected')==='true' && document.querySelector('[role=tabpanel]').innerText.includes('${expected}')`)}
 console.log('P5 사용자 흐름, 저장 실패 복구, 두 탭 충돌, 두 세션 격리, 문서·과목 복원, 분석 준비·5탭: 통과');
}finally{for(const p of pages)p.close();control?.close();processBrowser.kill();await delay(500);rmSync(tmp,{recursive:true,force:true})}

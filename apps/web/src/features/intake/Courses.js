'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Stepper, Heading } from '../../components/layout/Shell';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
import { SelectedCoursesSummary } from './CourseSelectionSummary';

const names={unavailable:'목록 사용 불가',unconfirmed:'미확인',confirmed:'이수 선택 확인 완료',partial:'일부 누락 · 부분 확인'};
export default function Courses(){
 const router=useRouter();
 const [requestId,setRequestId]=useState(null),[catalogId,setCatalogId]=useState(null),[data,setData]=useState(null),[phase,setPhase]=useState('loading'),[message,setMessage]=useState(''),[missing,setMissing]=useState(false);
 const [search,setSearch]=useState(''),[year,setYear]=useState(''),[category,setCategory]=useState(''),[only,setOnly]=useState(false),[page,setPage]=useState(1),[pageSize,setPageSize]=useState(20),[querySearch,setQuerySearch]=useState('');
 useEffect(()=>{if(search.trim()===querySearch)return;const timer=setTimeout(()=>{setPage(1);setQuerySearch(search.trim());},300);return()=>clearTimeout(timer)},[search,querySearch]);
 const lock=useRef(false), sequence=useRef(0), missingDirty=useRef(false);
 const load=useCallback(async(id,cid,filters)=>{
  const seq=++sequence.current;
  const query=new URLSearchParams({catalog_id:cid,page:String(filters.page),page_size:String(filters.pageSize),completed_only:String(filters.only)});
  if(filters.search.trim())query.set('q',filters.search.trim());if(filters.year)query.set('year',filters.year);if(filters.category)query.set('category',filters.category);
  const response=await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}/courses?${query}`);
  if(seq===sequence.current){setData(response);setPage(response.page);if(!missingDirty.current)setMissing(response.reported_missing_courses);return response;}
 },[]);
 const filters={search:querySearch,year,category,only,page,pageSize};
 useEffect(()=>{let active=true;(async()=>{try{const id=await resolvePlanId();if(!id){if(active)setPhase('empty');return;}const plan=await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}`);if(!active)return;setRequestId(id);if(!plan.input.catalog_id){setPhase('unavailable');return;}setCatalogId(plan.input.catalog_id);setPhase('ready');}catch(e){if(active){setPhase('failed');setMessage(e.message);}}})();return()=>{active=false;sequence.current++}},[]);
 useEffect(()=>{if(!requestId||!catalogId)return;let active=true;setPhase('loading');load(requestId,catalogId,{search:querySearch,year,category,only,page,pageSize}).then(()=>{if(active)setPhase('ready')}).catch(e=>{if(active){setPhase('failed');setMessage(e.message)}});return()=>{active=false;sequence.current++}},[requestId,catalogId,querySearch,year,category,only,page,pageSize,load]);
 async function refresh(){if(lock.current)return;lock.current=true;setPhase('loading');setMessage('');try{const plan=await apiRequest(`/roadmap-inputs/${encodeURIComponent(requestId)}`);if(!plan.input.catalog_id){setData(null);setCatalogId(null);setPhase('unavailable');return;}const cid=plan.input.catalog_id;setCatalogId(cid);missingDirty.current=false;await load(requestId,cid,filters);setPhase('ready');setMessage('최신 선택 상태를 불러왔습니다.');}catch(e){setPhase('failed');setMessage(e.message)}finally{lock.current=false}}
 async function mutate(action,body){if(lock.current || phase!=='ready')return;lock.current=true;sequence.current++;setPhase('saving');setMessage('저장 중입니다…');try{await apiRequest(`/roadmap-inputs/${encodeURIComponent(requestId)}/${action}`,{method:action==='course-selections'?'PATCH':'POST',body:JSON.stringify(body)});if(action==='course-selection-review')missingDirty.current=false;await load(requestId,catalogId,filters);setPhase('ready');setMessage(action==='course-selections'?'이수 선택이 저장되었습니다.':'현재 목록 전체의 확인 상태가 저장되었습니다.');}catch(e){setPhase('failed');setMessage(e.status===409?'다른 화면에서 선택이나 입력이 변경되었습니다. 최신 상태를 불러와 확인해 주세요.':e.message+' 저장 여부를 확인하려면 최신 상태를 불러와 주세요.')}finally{lock.current=false}}
 function toggle(courseId,target){mutate('course-selections',{catalog_id:catalogId,expected_selection_revision:data.selection_revision,changes:[{course_id:courseId,is_completed:target}]})}
 async function next(){
  if(lock.current||phase!=='ready'||missingDirty.current)return;
  lock.current=true;setPhase('loading');
  try{
   const plan=await apiRequest(`/roadmap-inputs/${encodeURIComponent(requestId)}`);
   if(!plan.input.catalog_id){setData(null);setCatalogId(null);setPhase('unavailable');return;}
   const latest=await load(requestId,plan.input.catalog_id,filters);setCatalogId(plan.input.catalog_id);
   if(!latest || !['confirmed','partial'].includes(latest.review_status)){setPhase('ready');setMessage('현재 목록 전체의 이수 선택을 먼저 확인해 주세요.');return;}
   router.push('/input/review');
  }catch(e){setPhase('failed');setMessage(e.message)}finally{lock.current=false}
 }
 async function continueWithoutCatalog(){
  if(lock.current||phase!=='unavailable')return;
  lock.current=true;setPhase('loading');
  try{
   const plan=await apiRequest(`/roadmap-inputs/${encodeURIComponent(requestId)}`);
   if(plan.input.catalog_id){setCatalogId(plan.input.catalog_id);setMessage('과목 목록 기준이 변경되었습니다. 이수 선택을 확인해 주세요.');return;}
   router.push('/input/review');
  }catch(e){setPhase('failed');setMessage(e.message)}finally{lock.current=false}
 }
 function confirm(){mutate('course-selection-review',{catalog_id:catalogId,expected_selection_revision:data.selection_revision,expected_input_revision:data.input_revision,reported_missing_courses:missing})}
 const busy=phase!=='ready';
 const filterDisabled=phase==='saving'||phase==='failed';
 return <><Stepper current={2} blockForward/><Heading number="04" title="이수 과목" description="학과 목록에서 이미 이수한 과목을 선택합니다. 수강 중인 과목은 이수 완료에 포함하지 않습니다."/>
 {phase==='loading'&&!data&&<div className="notice" role="status">과목 목록을 불러오는 중입니다.</div>}
 {phase==='empty'&&<div className="empty-state"><strong>계획이 없습니다.</strong><p>시작 화면에서 계획을 만들어 주세요.</p><Link className="button" href="/">시작 화면</Link></div>}
 {phase==='unavailable'&&<div className="empty-state"><strong>현재 학교·학과의 과목 목록을 사용할 수 없습니다.</strong><p>이 상태를 이수 과목 0개로 해석하지 않습니다. 기본 정보에서 학교·학과와 목록 기준을 확인해 주세요.</p><Link className="button" href="/input/basic">기본 정보 확인</Link></div>}
 {phase==='failed'&&<div className="notice" role="alert"><strong>목록 조회 또는 저장을 완료하지 못했습니다.</strong><br/>{message} {requestId?<button onClick={refresh}>최신 상태 불러오기</button>:<Link href="/">시작 화면</Link>}</div>}
 {data&&<><div className="select-note"><strong>{data.catalog_version}</strong><br/>{data.scope_description}<br/>원천 범위 상태: {data.completeness_status} · 출처: {data.source.name} · 확인: {data.source.retrieved_at}</div><div className="columns course-layout"><section className="wire-box"><h3>학과 과목 목록</h3><div className="filters"><input aria-label="과목명·코드 검색" placeholder="과목명·코드 검색" maxLength={100} value={search} disabled={filterDisabled} onChange={e=>setSearch(e.target.value)}/><select aria-label="학년 필터" value={year} disabled={filterDisabled} onChange={e=>{setPage(1);setYear(e.target.value)}}><option value="">전체 학년</option>{[1,2,3,4].map(y=><option key={y} value={y}>{y}학년</option>)}</select><select aria-label="전공 구분 필터" value={category} disabled={filterDisabled} onChange={e=>{setPage(1);setCategory(e.target.value)}}><option value="">전체 구분</option>{data.categories.map(c=><option key={c}>{c}</option>)}</select></div><label className="check-line"><input type="checkbox" checked={only} disabled={filterDisabled} onChange={e=>{setPage(1);setOnly(e.target.checked)}}/> 선택한 과목만 보기</label><div className="doc-actions"><label>페이지당 <select aria-label="페이지당 과목 수" value={pageSize} disabled={filterDisabled} onChange={e=>{setPage(1);setPageSize(Number(e.target.value))}}>{[10,20,50].map(n=><option key={n} value={n}>{n}개</option>)}</select></label><button disabled={filterDisabled} onClick={()=>{setSearch('');setQuerySearch('');setYear('');setCategory('');setOnly(false);setPage(1)}}>검색·필터 초기화</button></div><p className="field-help" role="status">{phase==='loading'||search.trim()!==querySearch?'검색 결과를 불러오는 중…':`검색 결과 ${data.total}개 · 전체 선택 ${data.selection_summary.count}개`}</p><div className="table-scroll" aria-busy={phase==='loading'}><table><thead><tr><th>과목명 · 과목코드</th><th>학점</th><th>구분 · 권장 학년/학기</th><th>이미 이수함</th></tr></thead><tbody>{data.courses.length?data.courses.map(c=><tr key={c.course_id}><td><strong>{c.course_name}</strong><br/><span className="field-help">{c.course_code||'코드 없음'}</span></td><td>{c.credits===null?'정보 없음':c.credits}</td><td>{c.category||'구분 없음'}<br/><span className="field-help">{c.recommended_year?`${c.recommended_year}학년`:''} {c.recommended_term||''}</span></td><td><button className="course-toggle" type="button" role="switch" aria-label={`${c.course_name} ${c.course_code||''} 이미 이수함`} aria-checked={c.is_completed} disabled={busy} onClick={()=>toggle(c.course_id,!c.is_completed)}><span className="toggle-track" aria-hidden="true"/><span>{c.is_completed?'선택됨':'미선택'}</span></button></td></tr>):<tr><td className="muted" colSpan="4">검색 결과가 없습니다. 검색어·필터를 초기화해 보세요. 기존 선택은 유지됩니다.</td></tr>}</tbody></table></div><div className="pagination"><button disabled={busy||page===1} onClick={()=>setPage(p=>p-1)}>이전 페이지</button><span>{page} / {Math.max(1,Math.ceil(data.total/data.page_size))}</span><button disabled={busy||page*data.page_size>=data.total} onClick={()=>setPage(p=>p+1)}>다음 페이지</button></div><p className="field-help">권장 학기와 실제 개설 학기는 다릅니다. 확인 전 미선택은 미이수를 뜻하지 않습니다.</p>{data.out_of_scope_completed_courses.length>0&&<details><summary>현재 목록 밖의 기존 선택 · {data.out_of_scope_completed_courses.length}개</summary><p className="field-help">이전 목록의 선택을 보관합니다. 이름이 같다는 이유로 다른 과목에 이전하지 않습니다.</p><ul>{data.out_of_scope_completed_courses.map(c=><li key={c.course_id}>{c.course_name} ({c.course_code||'코드 없음'}) <button disabled={busy} onClick={()=>toggle(c.course_id,false)}>선택 해제</button></li>)}</ul></details>}</section><aside className="wire-box"><h3>선택 현황</h3><SelectedCoursesSummary data={data}/><div className="notice">{names[data.review_status]}</div><label className="check-line"><input type="checkbox" checked={missing} disabled={busy} onChange={e=>{missingDirty.current=true;setMissing(e.target.checked);setMessage('누락 신고 변경은 이수 선택 확인 완료를 눌러 저장해 주세요.')}}/> 목록에 없는 이수 과목이 있어요</label><p className="field-help" role="status">{message || (phase==='saving'?'저장 중입니다…':'선택이 저장된 상태입니다.')}</p><button className="primary" disabled={busy} onClick={confirm}>이수 선택 확인 완료</button><p className="field-help">검색·필터와 관계없이 현재 목록 전체를 확인합니다. 0개를 선택해도 확인할 수 있습니다.</p></aside></div></>}
 <footer className="footer"><div><Link className="button" href="/input/documents">이전</Link><div className="footer-note">이수 선택을 변경하거나 목록 기준을 바꾸면 확인 상태가 해제됩니다.</div></div>{phase==='unavailable'?<button className="primary" onClick={continueWithoutCatalog}>수강 제안 없이 계속</button>:<button className="primary" disabled={busy||!data||!['confirmed','partial'].includes(data.review_status)||missingDirty.current} onClick={next}>다음: 분석 내용 확인</button>}</footer></>;
}

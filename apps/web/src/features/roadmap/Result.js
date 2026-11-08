'use client';
import { useState } from 'react';
import Link from 'next/link';
import { Heading } from '../../components/layout/Shell';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
const tabs = ['준비 상태','직무 역량 비교','실행 로드맵','수강 후보','공모전·대외활동'];
export default function Result() {
 const [selected, setSelected] = useState(0);
 const [phase,setPhase]=useState('idle'), [message,setMessage]=useState(''), [result,setResult]=useState(null), [goal,setGoal]=useState('');
 function onKeyDown(e) { let next; if (e.key === 'ArrowRight') next = (selected + 1) % tabs.length; else if (e.key === 'ArrowLeft') next = (selected + tabs.length - 1) % tabs.length; else if (e.key === 'Home') next = 0; else if (e.key === 'End') next = tabs.length - 1; else return; e.preventDefault(); setSelected(next); document.getElementById(`tab-${next}`)?.focus(); }
 async function generate() {
  setPhase('loading'); setMessage(''); setResult(null);
  try {
   const id=await resolvePlanId();
   if(!id)throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.');
   const data=await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}/course-recommendations`,{method:'POST',body:'{}'});
   setGoal(data.career_goal || ''); setResult(data); setPhase('ready');
  } catch(e){setMessage(e.message);setPhase('error');}
 }
 return <><div className="result-head"><Heading number="06" title="로드맵 결과" description="입력 기준에 따른 결과 화면입니다."/><Link href="/input/basic" className="button">입력 수정</Link></div><div className="result-summary"><div><span>진로 목표</span><strong>{goal || '결과 생성 전'}</strong></div><div><span>생성 당시 입력 기준</span><strong>{result ? `입력 버전 ${result.input_revision}` : '표시할 기준 없음'}</strong></div></div><div className="result-tabs" role="tablist" aria-label="결과 구성" onKeyDown={onKeyDown}>{tabs.map((tab,i)=><button key={tab} role="tab" id={`tab-${i}`} aria-controls="result-panel" aria-selected={selected===i} tabIndex={selected===i?0:-1} onClick={()=>setSelected(i)}>{tab}</button>)}</div><section id="result-panel" role="tabpanel" aria-labelledby={`tab-${selected}`} className="empty-state">{selected===3 ? <><strong>수강 후보</strong><p>저장된 진로 목표와 과목 목록을 바탕으로 후보를 확인합니다.</p>{phase==='loading'&&<p role="status">과목을 분석하고 있습니다…</p>}{phase==='error'&&<p role="alert">{message}</p>}{result && (result.courses.length ? <ul>{result.courses.map(c=><li key={c.course_id}>{c.course_name}{c.category ? ` · ${c.category}` : ''}{c.recommended_year ? ` · ${c.recommended_year}학년` : ''}{c.recommended_term ? ` ${c.recommended_term}` : ''}</li>)}</ul> : <p role="status">{result.status==='empty_catalog' ? '선택한 과목 목록에 과목이 없습니다.' : '추천할 만한 과목이 없습니다.'}</p>)}{result?.review_status==='unconfirmed'&&<p className="field-help">이수 목록을 아직 확인하지 않아 선택하지 않은 과목의 이수 여부는 확정되지 않았습니다.</p>}<button className="primary" onClick={generate} disabled={phase==='loading'}>{result?'다시 분석':'수강 후보 분석'}</button></> : <><strong>아직 생성된 분석 결과가 없습니다</strong><p>{tabs[selected]} 결과가 생성되면 이곳에서 확인할 수 있습니다.</p><button className="primary" disabled>로드맵 생성</button></>}</section><footer className="footer"><span className="field-help">수강 후보 외 분석과 결과 생성 기능을 준비 중입니다.</span><Link className="button" href="/input/basic">입력 수정</Link></footer></>;
}

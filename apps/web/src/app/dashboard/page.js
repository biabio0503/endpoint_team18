'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';

export default function Dashboard() {
 const [data,setData]=useState(null), [phase,setPhase]=useState('loading'), [message,setMessage]=useState(''), [retry,setRetry]=useState(0);
 useEffect(()=>{
  let active=true;
  setPhase('loading');
  (async()=>{
   try {
    const id=await resolvePlanId();
    if(!active)return;
    if(!id){setPhase('empty');return;}
    const plan=await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}`);
    if(!active)return;
    setData(plan);setPhase('ready');
   }catch(e){if(active){setMessage(e.message);setPhase('error');}}
  })();
  return()=>{active=false;};
 },[retry]);
 return <>
  <div className="eyebrow">MY CAREER</div><h1 className="page-title">대시보드</h1><p className="description">서버에 저장한 진로 목표를 확인하고, 이어서 나의 계획을 완성해 보세요.</p>
  {phase==='loading'&&<p className="notice" role="status">저장한 계획을 불러오는 중입니다…</p>}
  {phase==='error'&&<div className="notice" role="alert">{message} <button onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button> <Link href="/">계정 확인</Link></div>}
  {phase==='empty'&&<div className="empty-state"><strong>아직 작성한 계획이 없어요</strong><p>시작 화면에서 로그인하고 새로운 계획을 작성해 주세요.</p><Link className="button primary" href="/">계획 시작하기</Link></div>}
  {phase==='ready'&&<><div className="columns"><section className="wire-box"><h3>나의 진로 방향</h3><p className="dashboard-goal">{data.input.career_goal||'아직 관심 분야를 입력하지 않았어요.'}</p><p className="field-help">희망 직무 · {data.input.target_role||'아직 정하지 않았어요'}</p><Link className="button primary" href="/input/basic">기본 정보 수정하기</Link></section><section className="wire-box"><h3>나의 로드맵</h3><p className="description">저장된 분석과 생성 이력을 확인하고 다음 할 일을 기록하세요.</p><Link className="button primary" href="/result">로드맵 결과 보기</Link></section></div>
  <div className="dashboard-links">{[['/input/documents','▤','경험 · 문서','문서 등록, 읽기 상태와 추출 내용 확인'],['/input/courses','▧','이수 과목','교육과정 검색과 이수 선택 확인'],['/input/review','✧','역량 탐색','프로젝트 경험 분석과 내 역할 확인']].map(([href,icon,title,detail])=><Link key={href} href={href} className="step-card"><i aria-hidden="true">{icon}</i><b>{title}</b><p>{detail}</p><span aria-hidden="true">↗</span></Link>)}</div></>}
 </>;
}

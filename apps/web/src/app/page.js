'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { apiRequest } from '../lib/api/client';
export default function Home() {
 const router=useRouter(); const [busy,setBusy]=useState(false); const [message,setMessage]=useState('');
 async function open(resume) { setBusy(true); setMessage(''); try { const data=await apiRequest(resume?'/roadmap-inputs/resume':'/roadmap-inputs', resume?{}:{method:'POST'}); if(resume&&!data.found){setMessage('이어서 작성할 계획이 없습니다. 새 계획을 시작해 주세요.');return;} const id=resume?data.request.request_id:data.request_id; sessionStorage.setItem('roadmap_request_id',id); router.push('/input/basic'); } catch(error){setMessage(error.message)} finally{setBusy(false)} }
 return <div className="start-wrap"><div className="start-wire"><span className="design-label">서비스 소개</span><h1>나의 경험에서 다음 준비까지</h1><p>진로 목표, 프로젝트 경험과 이수 과목을 연결해 무엇을 어떤 순서로 준비할지 안내하는 서비스입니다.</p></div><h2 className="section-title">시작 전에 준비할 정보</h2><div className="start-inputs">{[['진로 목표','관심 분야와 희망 진로'],['프로젝트 문서','본인 역할과 활동이 담긴 문서'],['학업 현황','학교·학과·학년과 과목 목록 기준'],['이수한 과목','학과 과목 목록에서 이미 이수한 과목']].map(([title, description]) => <div className="start-input" key={title}><strong>{title}</strong><p>{description}</p></div>)}</div><div className="start-action"><button className="primary" disabled={busy} onClick={()=>open(false)}>{busy?'처리 중…':'새 계획 시작'}</button><button disabled={busy} onClick={()=>open(true)}>이어서 작성</button><Link className="button" href="/result">결과 화면 보기</Link></div>{message&&<p className="notice" role="status">{message}</p>}<div className="support-note">기본 정보, 문서와 이수 선택은 이 브라우저의 세션에 저장됩니다. 분석 기능은 준비 중입니다.</div></div>;
}

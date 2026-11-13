'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { apiRequest } from '../lib/api/client';
import { authClient } from '../lib/api/auth';
import { clearSelectedPlan, selectPlan, readResume } from '../lib/api/session';

export default function Home() {
 const router = useRouter();
 const [busy, setBusy] = useState(true);
 const [message, setMessage] = useState('');
 const [user, setUser] = useState(null);
 const [planStatus, setPlanStatus] = useState({ userId: null, phase: 'loading' });
 const [retry, setRetry] = useState(0);
 const lock = useRef(false);

 useEffect(() => {
  let subscription, active = true, authEventReceived = false;
  try {
   const auth = authClient().auth;
   const params = new URLSearchParams(window.location.hash.slice(1));
   const query = new URLSearchParams(window.location.search);
   if (params.get('error') || query.get('error')) {
    setMessage('Google 인증을 완료하지 못했습니다. 다시 시도해 주세요.');
    window.history.replaceState({}, '', window.location.pathname);
   }
   subscription = auth.onAuthStateChange((_event, session) => {
    authEventReceived = true;
    if (!session) clearSelectedPlan();
    setUser(session?.user || null);
    if (!lock.current) setBusy(false);
   }).data.subscription;
   auth.getSession().then(({ data, error }) => {
    if (!active || authEventReceived) return;
    if (error) setMessage('세션을 확인하지 못했습니다. 다시 로그인해 주세요.');
    if (!data.session) clearSelectedPlan();
    setUser(data.session?.user || null);
    setBusy(false);
   }).catch(() => { if (active) { setMessage('세션을 확인하지 못했습니다. 다시 로그인해 주세요.'); setBusy(false); } });
  } catch (e) { setMessage(e.message); setBusy(false); }
  return () => { active = false; subscription?.unsubscribe(); };
 }, []);

 useEffect(() => {
  if (!user?.id) return;
  let active = true;
  const userId = user.id;
  setPlanStatus({ userId, phase: 'loading' });
  readResume(userId).then(data => {
   if (active) setPlanStatus({ userId, phase: data.found ? 'found' : 'empty' });
  }).catch(error => {
   if (active) setPlanStatus({ userId, phase: 'error', message: error.message });
  });
  return () => { active = false; };
 }, [user?.id, retry]);

 async function google() {
  if (lock.current) return;
  lock.current = true; setBusy(true); setMessage('');
  try {
   const { error } = await authClient().auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin + '/' } });
   if (error) throw error;
  } catch (e) {
   setMessage(`Google 로그인 오류: ${e?.message || '알 수 없는 오류'}`);
   setBusy(false); lock.current = false;
  }
 }
 async function guest() {
  if (lock.current) return;
  lock.current = true; setBusy(true); setMessage('');
  try {
   const { error } = await authClient().auth.signInAnonymously();
   if (error) throw error;
  } catch (e) { setMessage(e.message || '게스트 인증에 실패했습니다.'); }
  finally { setBusy(false); lock.current = false; }
 }
 async function openPlan(create) {
  if (lock.current || !user?.id) return;
  lock.current = true; setBusy(true); setMessage('');
  try {
   const userId = user.id;
   const data = create
    ? await apiRequest('/roadmap-inputs', { method: 'POST', expectedUserId: userId })
    : await readResume(userId);
   if (!create && !data.found) {
    setPlanStatus({ userId, phase: 'empty' });
    setMessage('이어 쓸 계획을 찾지 못했습니다. 새 계획을 작성해 주세요.');
    setBusy(false); lock.current = false; return;
   }
   const requestId = create ? data.request_id : data.request.request_id;
   if (typeof requestId !== 'string' || !requestId) throw new Error('계획 응답을 확인할 수 없습니다. 다시 시도해 주세요.');
   await selectPlan(requestId, userId);
   router.push('/input/basic');
  } catch (e) { setMessage(e.message || '계획을 열지 못했습니다. 다시 시도해 주세요.'); setBusy(false); lock.current = false; }
 }
 async function logout() {
  if (lock.current) return;
  if (user?.is_anonymous && !window.confirm('게스트 세션을 종료하면 이 데이터를 자동으로 복원할 수 없습니다. 로그아웃할까요?')) return;
  lock.current = true; setBusy(true);
  try {
   const { error } = await authClient().auth.signOut();
   if (error) throw error;
   clearSelectedPlan(); setMessage('로그아웃했습니다.');
  } catch (e) { setMessage('로그아웃하지 못했습니다. 다시 시도해 주세요.'); }
  finally { setBusy(false); lock.current = false; }
 }
 const phase = planStatus.userId === user?.id ? planStatus.phase : 'loading';
 return <div className="home-page">
  <section className="home-hero">
   <div className="home-copy"><div className="home-eyebrow">MY CAREER, ONE STEP UP</div><h1>어떤 일을<br/>해 보고 싶나요?</h1><p className="lead">관심 분야를 적으면 프로젝트 경험과 이수 과목을 연결해 다음 할 일을 정리할 수 있어요.</p>
    <div className="start-action home-actions">{user?<>
     <p className="session-label">{user.is_anonymous?'게스트 이용 중':`로그인됨${user.email?' · '+user.email:''}`}</p>
     {phase==='loading'&&<span role="status">저장된 계획을 확인하고 있습니다…</span>}
     {phase==='error'&&<><span role="status">저장된 계획을 확인하지 못했습니다. {planStatus.message}</span><button disabled={busy} onClick={()=>setRetry(value=>value+1)}>다시 확인</button></>}
     {(phase==='empty'||phase==='error')&&<button className="primary" disabled={busy} onClick={()=>openPlan(true)}>작성하기</button>}
     {phase==='found'&&<><button className="primary" disabled={busy} onClick={()=>openPlan(false)}>이어서 작성</button><button disabled={busy} onClick={()=>openPlan(true)}>처음부터 작성하기</button></>}
     <button disabled={busy} onClick={logout}>로그아웃</button>
    </>:<><button className="primary" disabled={busy} onClick={google}>Google로 계속하기</button><button disabled={busy} onClick={guest}>로그인 없이 시작하기</button></>}
    {user&&phase==='found'&&<Link className="button saved-result-link" href="/result">저장 결과·분석 단계로 이동</Link>}</div>
    {message&&<p className="notice" role="status">{message}</p>}
    <p className="home-hint">직무가 정해지지 않아도 괜찮아요. 시작한 뒤 관심 분야부터 적어 보세요.</p>
   </div>
   <aside className="preview-card" aria-label="계획 예시"><div className="preview-label">완성된 계획 예시 <span aria-hidden="true">▤</span></div><h2>백엔드 개발자</h2><div className="progress-art" aria-hidden="true"><span>■</span><span>○</span><span>◇</span></div>{[['내 프로젝트','동아리 행사 신청 서비스'],['확인한 경험','신청 API의 중복 처리 구현'],['다음 할 일','집계 SQL의 담당 범위 확인']].map(([a,b])=><div className="preview-row" key={a}><span>{a}</span><b>{b}</b></div>)}<p className="field-help">화면 이해를 돕기 위한 예시입니다.<br/>내 로드맵은 저장한 정보와 분석 결과로 만들어집니다.</p></aside>
  </section>
  <section className="steps-wrap"><h2>계획 작성 순서</h2><div className="home-steps">{[['◎','진로와 학교','관심 분야와 교육과정 선택'],['▤','프로젝트 자료','내 역할을 설명하는 문서 등록'],['▧','이수 과목','학과 목록에서 이수 여부 확인'],['✧','내 역할 확인','경험과 연결된 역량 살펴보기']].map(([icon,title,description])=><div className="step-card" key={title}><i aria-hidden="true">{icon}</i><b>{title}</b><p>{description}</p></div>)}</div></section>
  <div className="support-note">게스트는 같은 브라우저의 세션으로 다시 이용할 수 있습니다. 세션을 잃거나 로그아웃하면 데이터를 자동 복원할 수 없습니다. Google 계정은 다른 기기에서도 복원할 수 있습니다.</div>
 </div>;
}

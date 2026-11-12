'use client';
import { useEffect, useRef, useState } from 'react';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
import { activityKindLabel, createActivityLoader } from './activityLoader.mjs';

export default function ActivityRecommendations({ active, inputRevision, onResult }) {
 const loader = useRef(null), refresh = useRef(false);
 if (!loader.current) loader.current = createActivityLoader({ apiRequest, resolvePlanId });
 const [state, setState] = useState({ phase: 'idle', data: null, message: '' });
 const [retry, setRetry] = useState(0);
 useEffect(() => {
  if (!active) return;
  let disposed = false, busy = false;
  async function load() {
   if (disposed || busy || document.visibilityState === 'hidden') return;
   busy = true;
   setState({ phase: 'loading', data: null, message: '' });
   const force = refresh.current; refresh.current = false;
   try {
    const data = await loader.current({ refresh: force });
    if (!disposed) { setState({ phase: 'ready', data, message: '' }); onResult(data); }
   } catch (error) {
    if (!disposed) { setState({ phase: 'error', data: null, message: error.message }); onResult(null); }
   } finally { busy = false; }
  }
  load();
  window.addEventListener('focus', load);
  document.addEventListener('visibilitychange', load);
  // Recheck eligibility while the tab remains open, including at midnight in Korea.
  const timer = setInterval(load, 60000);
  return () => {
   disposed = true; clearInterval(timer);
   window.removeEventListener('focus', load);
   document.removeEventListener('visibilitychange', load);
  };
 }, [active, inputRevision, retry, onResult]);
 const { phase, data, message } = state;
 const failed = data?.sources?.filter(source => source.status !== 'success') || [];
 return <div hidden={!active} className="activity-recommendations" aria-busy={phase === 'loading'}>
  <h2>공모전·대외활동 추천</h2>
  <p>저장한 진로 목표를 바탕으로, 한국 시간 기준 접수 중이거나 접수 예정이고 대학생 또는 누구나 참여 대상으로 안내된 공고를 추천합니다. 문서나 직무 분석 없이도 이용할 수 있습니다.</p>
  <button disabled={phase === 'loading'} onClick={() => { refresh.current = true; setRetry(v => v + 1); }}>활동 추천 다시 확인</button>
  {phase === 'loading' && <p role="status">접수 기간과 목표에 맞는 실제 공고를 확인하고 있습니다…</p>}
  {phase === 'error' && <p role="alert">{message}</p>}
  {data?.status === 'error' && <p role="alert">공모전·대외활동 공급자 조회에 실패했습니다. 잠시 후 다시 확인해 주세요.</p>}
  {failed.map(source => <p key={`${source.source || 'contestkorea'}-${source.kind}`} className="notice" role="status">
   {source.source === 'dacon_daker' ? '데이콘·데이커' : '콘테스트코리아'}: {source.error_code === 'last_collection_failed' ? '최근 수집에 실패하여 마지막 성공 자료에서 접수 중이거나 예정인 공고를 표시합니다.' : source.error_code === 'not_configured' ? '공급자 연결이 아직 설정되지 않았습니다.' : source.status === 'partial' ? '일부 분야 또는 접수 기간을 확인하지 못해 검증된 공고만 표시합니다.' : '공급자에서 공고를 가져오지 못했습니다.'}
  </p>)}
  {data && data.status !== 'error' && data.activities.length === 0 && <p role="status">{data.status === 'partial' ? '정상 조회된 공고 중 ' : ''}현재 추천 조건에 맞는 공고가 없습니다. 목표 관련성, 접수 기간과 참가 대상을 확인한 공고만 표시합니다.</p>}
  {data && <>
   <p className="field-help">{data.sample_notice}</p>
   <p className="field-help">판정 시각: {new Date(data.evaluated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} (한국 시간) · 각 출처의 마지막 성공 수집 자료를 조회하며, 접수 마감은 조회 시점에 다시 확인합니다.</p>
   <ul className="skill-list">{data.activities.map(item => <li key={item.id} className="skill-card">
    <div className="skill-title"><span className="badge">{activityKindLabel(item.kind)}</span><span className="badge">{item.status === 'upcoming' ? '접수 예정' : '접수 중'}</span><h3>{item.title}</h3></div>
    <dl className="skill-summary">
     <div><dt>출처</dt><dd>{item.source_label || '콘테스트코리아'}</dd></div>
     <div><dt>분야</dt><dd>{item.category || '공급자 미제공'}</dd></div>
     <div><dt>주최·주관</dt><dd>{item.host || '공급자 미제공'}</dd></div>
     <div><dt>참가 대상</dt><dd>{item.target}</dd></div>
     {item.status === 'upcoming' && item.opens_at && <div><dt>접수 시작</dt><dd>{new Date(item.opens_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })} (한국 시간)</dd></div>}
     <div><dt>접수 마감</dt><dd>{item.deadline_label}</dd></div>
     <div><dt>접수 기간 원문</dt><dd>{item.period}</dd></div>
     {item.verified_period && <div><dt>원문에서 확인한 기간</dt><dd>{item.verified_period}</dd></div>}
    </dl>
    <h4>추천 이유</h4>
    {item.reasons.map((reason, i) => <p key={i}>{reason}</p>)}
    <a className="button" href={item.url} target="_blank" rel="noopener noreferrer" aria-label={`${item.title} 원문 보기 (새 창)`}>원문 보기 <span aria-hidden="true">↗</span></a>
   </li>)}</ul>
  </>}
 </div>;
}

'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import JobSkillAnalysis from './JobSkillAnalysis';
import ActivityRecommendations from './ActivityRecommendations';
import { Preparation, RoadmapSteps, CourseCandidates } from './RoadmapPanels';
import { Heading } from '../../components/layout/Shell';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
import { roadmapErrorMessage } from './roadmapErrors.mjs';

const tabs = ['준비 상태', '직무 역량 비교', '실행 로드맵', '수강 후보', '공모전·대외활동'];
export default function Result() {
 const [selected, setSelected] = useState(0), [plan, setPlan] = useState(null);
 const [result, setResult] = useState(null), [history, setHistory] = useState([]);
 const [phase, setPhase] = useState('loading'), [message, setMessage] = useState('');
 const [saving, setSaving] = useState(false), [skillResult, setSkillResult] = useState(null);
 const [activityResult, setActivityResult] = useState(null);
 const epoch = useRef(0), selectedRun = useRef(''), generating = useRef(false);
 const load = useCallback(async (runId = selectedRun.current) => {
  const ticket = ++epoch.current;
  try {
   const id = await resolvePlanId();
   if (!id) throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.');
   const base = `/roadmap-inputs/${encodeURIComponent(id)}`;
   const [input, data, runs] = await Promise.all([
    apiRequest(base), apiRequest(runId ? `${base}/roadmaps/${encodeURIComponent(runId)}` : `${base}/roadmap`), apiRequest(`${base}/roadmaps`),
   ]);
   if (ticket !== epoch.current) return;
   setPlan(input); setResult(data); setHistory(runs.runs || []); setPhase('ready');
  } catch (error) {
   if (ticket !== epoch.current) return;
   setResult(null); setPlan(null); setHistory([]); setMessage(error.message); setPhase('error');
  }
 }, []);
 useEffect(() => { load(); return () => { epoch.current++; }; }, [load]);
 useEffect(() => {
  const refresh = () => { if (phase !== 'generating' && !saving) load(); };
  window.addEventListener('focus', refresh);
  return () => window.removeEventListener('focus', refresh);
 }, [load, phase, saving]);
 const pending = history.some(r => r.status === 'generating' && !r.generation_expired);
 useEffect(() => {
  if (!pending || phase === 'generating') return;
  const timer = setInterval(() => load(), 5000);
  return () => clearInterval(timer);
 }, [pending, phase, load]);
 const onSkillResult = useCallback(data => { setSkillResult(data); if (data && !generating.current) load(); }, [load]);
 function changeTab(index) { setSelected(index); if (phase !== 'generating' && !saving) load(); }
 function onKeyDown(e) {
  let next;
  if (e.key === 'ArrowRight') next = (selected + 1) % tabs.length;
  else if (e.key === 'ArrowLeft') next = (selected + tabs.length - 1) % tabs.length;
  else if (e.key === 'Home') next = 0;
  else if (e.key === 'End') next = tabs.length - 1;
  else return;
  e.preventDefault(); changeTab(next); document.getElementById(`tab-${next}`)?.focus();
 }
 async function generate(refresh) {
  if (!plan || generating.current) return;
  generating.current = true; ++epoch.current; setPhase('generating'); setMessage('');
  try {
   const data = await apiRequest(`/roadmap-inputs/${plan.request_id}/roadmap`, {
    method: 'POST', body: JSON.stringify({ expected_input_revision: plan.input_revision, refresh }),
   });
   selectedRun.current = ''; setResult(data); setSelected(2);
   await load('');
  } catch (error) { setMessage(roadmapErrorMessage(error)); await load(); }
  finally { generating.current = false; }
 }
 async function toggle(task) {
  ++epoch.current; setSaving(true); setMessage('');
  try {
   const data = await apiRequest(`/roadmap-inputs/${plan.request_id}/roadmaps/${result.run_id}/tasks/${encodeURIComponent(task.task_id)}`, {
    method: 'PATCH', body: JSON.stringify({ is_completed: !task.is_completed, expected_progress_version: task.progress_version }),
   });
   setResult(data);
  } catch (error) { setMessage(error.message); await load(result.run_id); }
  finally { setSaving(false); }
 }
 const usable = result?.roadmap && !result.details_restricted;
 const busy = phase === 'generating' || phase === 'loading' || saving;
 const displayed = selected === 4 ? activityResult : selected === 1 ? skillResult : result;
 const displayedGoal = displayed?.career_goal || plan?.input?.career_goal;
 return <>
  <div className="result-head"><Heading number="06" title="로드맵 결과" description="입력 기준에 따른 결과 화면입니다."/><Link href="/input/basic" className="button">입력 수정</Link></div>
  <div className="result-summary"><div><span>진로 목표</span><strong>{displayedGoal || '입력 확인 중'}</strong></div><div><span>{selected === 4 ? '추천에 사용한 입력 기준' : '생성 당시 입력 기준'}</span><strong>{displayed?.run_id || [1, 4].includes(selected) && displayed ? `입력 버전 ${displayed.input_revision}` : '표시할 기준 없음'}</strong></div></div>
  <p className="notice">진행 순서: 입력·프로젝트 경험 확인 → 직무 역량 비교에서 분석 실행 → 로드맵 생성. 외부 분석이 어려우면 제한 안내를 먼저 저장할 수 있습니다. 공모전·대외활동은 진로 목표만으로 바로 확인할 수 있습니다.</p>
  <div className="result-tabs" role="tablist" aria-label="결과 구성" onKeyDown={onKeyDown}>{tabs.map((tab, i) => <button key={tab} role="tab" id={`tab-${i}`} aria-controls="result-panel" aria-selected={selected === i} tabIndex={selected === i ? 0 : -1} onClick={() => changeTab(i)}>{tab}</button>)}</div>
  <section id="result-panel" role="tabpanel" aria-labelledby={`tab-${selected}`} className="empty-state skill-panel">
   <JobSkillAnalysis active={selected === 1} onResult={onSkillResult}/>
   <ActivityRecommendations active={selected === 4} inputRevision={plan?.input_revision} onResult={setActivityResult}/>
   {selected !== 1 && selected !== 4 && <>
    <div className="doc-actions roadmap-controls"><button className="primary" onClick={() => generate(false)} disabled={busy || pending || !plan}>{result?.limited_guidance_available ? '제한 안내 로드맵 생성' : '로드맵 생성'}</button>
     {history.some(r => ['success', 'partial'].includes(r.status)) && <button onClick={() => generate(true)} disabled={busy || pending || !plan}>현재 입력으로 다시 분석</button>}
     <button onClick={() => load()} disabled={busy}>저장 결과 새로고침</button>
    </div>
    <p className="field-help">직무 근거가 있는 로드맵 생성은 확인된 분석 요약과 과목 정보를 Gemini에 전달합니다. 제한 안내는 AI 호출 없이 저장됩니다. 같은 기준의 저장 결과는 재사용하며, AI 다시 분석은 새 실행 이력을 만듭니다. 같은 기준의 제한 안내는 재사용합니다.</p>
    {phase === 'loading' && <p role="status">저장된 결과를 불러오고 있습니다…</p>}
    {phase === 'generating' && <p role="status">확인된 경험과 과목 정보를 바탕으로 로드맵을 생성하고 있습니다…</p>}
    {message && <p role="alert">{message}</p>}
    {(result?.limited_guidance_available || result?.status === 'needs_job_analysis') && <div className="notice">검증된 직무 분석이 없어 진로 목표·교육과정 기준의 수강 후보와 제한 안내를 제공합니다. 기술별 준비 상태는 판단하지 않습니다. <button onClick={() => changeTab(1)}>직무 역량 비교에서 분석하기</button></div>}
    {pending && phase !== 'generating' && <p role="status">진행 중인 생성 요청이 있습니다. 저장 결과를 확인하고 있습니다.</p>}
    {result?.generation_expired && <p role="status">이전 생성 요청의 유효 시간이 지났습니다. 다시 생성할 수 있습니다.</p>}
    {history.length > 0 && <label className="field">결과 이력<select aria-label="결과 이력" value={selectedRun.current} disabled={busy} onChange={e => { selectedRun.current = e.target.value; load(e.target.value); }}>
     <option value="">최신 유효 결과 우선</option>{history.map(r => <option key={r.run_id} value={r.run_id}>{new Date(r.created_at).toLocaleString('ko-KR')} · 입력 {r.input_revision} · {r.status === 'failed' ? '생성 실패' : r.status === 'generating' ? '생성 중' : r.is_stale ? '이전 기준' : '현재 기준'}{r.details_restricted ? ' · 상세 제한' : ''}</option>)}
    </select></label>}
    {result?.run_id && <p className="field-help">{result.finished_at ? '생성 처리 완료' : '생성 요청'} 시각 {new Date(result.finished_at || result.created_at).toLocaleString('ko-KR')} · 입력 버전 {result.input_revision} · 현재 입력 버전 {result.current_input_revision} · {result.generation_mode === 'limited_guidance' ? 'AI 호출 없는 제한 안내' : result.model_name}</p>}
    {result?.is_stale && <p className="notice" role="status">이 결과는 이전 입력·분석 기준입니다. 현재 입력으로 다시 분석하면 새 이력이 생성되며 완료 체크는 옮겨지지 않습니다.</p>}
    {result?.details_restricted && <p className="notice">문서 삭제·재추출 등으로 근거가 변경되어 과거 결과의 상세 내용과 완료 체크 접근을 제한했습니다.</p>}
    {result?.status === 'failed' && <p role="status">{roadmapErrorMessage(result)}</p>}
    {usable ? selected === 0 ? <Preparation result={result}/> : selected === 2 ? <RoadmapSteps result={result} saving={busy} onToggle={toggle}/> : <CourseCandidates result={result}/> : !result?.details_restricted && <p>아직 표시할 로드맵 결과가 없습니다. 분석 근거를 확인한 후 로드맵을 생성해 주세요.</p>}
   </>}
  </section>
  <footer className="footer"><span className="field-help">완료 체크는 실행 기록이며 기술 숙련도나 취업 준비 점수가 아닙니다.</span><Link className="button" href="/input/review">경험 확인·수정</Link></footer>
 </>;
}

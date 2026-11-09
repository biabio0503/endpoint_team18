'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
import { createJobSkillLoader } from './jobSkillAnalysis.mjs';
import ProjectEvidence, { statusLabels } from './ProjectEvidence';

const requirementLabels = { required: '필수', preferred: '우대', mentioned: '단순 언급', unknown: '판단 불가' };
const categoryLabels = { programming_language: '프로그래밍 언어', database_query_language: '쿼리 언어', framework: '프레임워크', database: '데이터베이스', cloud: '클라우드', devops: '개발·운영', development_tool: '개발 도구', data_ai: '데이터·AI', technical_competency: '기술 역량', other: '기타 기술' };
const levelLabels = { entry: '초급', mid: '중급', senior: '고급', unknown: '경력 미확인' };

export default function JobSkillAnalysis({ active, onResult }) {
 const loader = useRef(null);
 if (!loader.current) loader.current = createJobSkillLoader({ apiRequest, resolvePlanId });
 const sequence = useRef(0);
 const [state, setState] = useState({ phase: 'idle', data: null, message: '' });
 const [retry, setRetry] = useState(0);
 const [saving, setSaving] = useState(false);
 const forceNext = useRef(false);
 useEffect(() => {
  if (!active) return;
  let disposed = false;
  let busy = false;
  async function load() {
   if (disposed || busy || document.visibilityState === 'hidden') return;
   busy = true;
   const attempt = ++sequence.current;
   setState({ phase: 'loading', data: null, message: '' });
   onResult(null);
   const force = forceNext.current;
   forceNext.current = false;
   try {
    const data = await loader.current({ force });
    if (!disposed && sequence.current === attempt) {
     setState({ phase: 'ready', data, message: '' });
     onResult(data);
    }
   } catch (error) {
    if (!disposed && sequence.current === attempt) setState({ phase: 'error', data: null, message: error.message });
   } finally { busy = false; }
  }
  load();
  window.addEventListener('focus', load);
  document.addEventListener('visibilitychange', load);
  return () => {
   disposed = true;
   window.removeEventListener('focus', load);
   document.removeEventListener('visibilitychange', load);
  };
 }, [active, retry, onResult]);
 const { phase, data, message } = state;
 const summary = data?.analysis_summary;
 async function answerSkill(skill, status) {
  setSaving(true);
  try {
   if (await resolvePlanId() !== data.request_id) throw new Error('계획이 변경되었습니다. 최신 내용을 불러와 주세요.');
   await apiRequest(`/roadmap-inputs/${encodeURIComponent(data.request_id)}/skill-comparison/answers`, { method: 'POST', body: JSON.stringify({ expected_input_revision: data.input_revision, snapshot_id: data.comparison.job_analysis.snapshot_id, skill_name: skill.name, status }) });
   setRetry(v => v + 1);
  } catch (error) { setState({ phase: 'error', data: null, message: error.message }); onResult(null); }
  finally { setSaving(false); }
 }
 return <div hidden={!active} className="job-skills" aria-busy={phase === 'loading'}>
  <strong>채용공고 기술 스택 분석</strong>
  <p>저장된 목표와 희망 직무를 바탕으로 해외 원격근무 공고의 기술을 살펴봅니다.</p>
  {phase === 'loading' && <p role="status">직무 검색어 생성 → 채용공고 수집 → 기술 및 원문 근거 분석 중입니다. 잠시 기다려 주세요…</p>}
  {phase === 'error' && <p role="alert">{message}</p>}
  {data && <>
   <dl className="skill-summary">
    <div><dt>분석 대상 직무</dt><dd>{data.canonical_role || data.target_role || '직무 확인 필요'}</dd></div>
    <div><dt>사용한 검색어</dt><dd>{data.keyword_details.length ? data.keyword_details.map(k => <span className="badge" key={k.keyword}>{k.keyword} · {k.relation === 'direct' ? '직접 관련' : '연관 직무'}</span>) : '검색 전'}</dd></div>
    <div><dt>채용공고 표본</dt><dd>선정 {data.collection_summary.selected_jobs}개 · 분석 성공 {summary.analyzed_jobs}개 · 실패 {summary.failed_jobs}개 · 건너뜀 {summary.skipped_jobs}개</dd></div>
    {data.retrieved_at && <div><dt>조회 시각</dt><dd>{new Date(data.retrieved_at).toLocaleString('ko-KR')}</dd></div>}
   </dl>
   {data.status === 'partial' && <p className="notice" role="status">일부 수집·분석 또는 근거 검증이 완료되지 않았습니다. 확인된 결과만 표시합니다.</p>}
   {data.refresh_error && <p role="alert">다시 분석을 완료하지 못해 이전 검증 결과를 유지했습니다. {data.refresh_error.errors.find(e => e.message)?.message}</p>}
   {data.snapshot_id && <p className="field-help">직무 분석 당시 입력 버전 {data.analyzed_input_revision} · 현재 비교 입력 버전 {data.input_revision} · {data.reused ? '저장된 직무 분석 재사용' : '직무 분석 저장 완료'}</p>}
   {data.comparison?.project_analysis && <div className="notice">프로젝트 문서 {data.comparison.project_analysis.analyzed_documents}개 분석 · 원문 검증 경험 {data.comparison.project_analysis.verified_experiences}개. {data.comparison.project_analysis.status === 'no_documents' ? '분석 가능한 문서가 없어 경험 정보를 확인할 수 없습니다.' : data.comparison.project_analysis.status !== 'success' ? '프로젝트 분석이 미실행 또는 일부 미완료 상태입니다.' : '확인하지 않은 항목은 미확인 상태로 표시합니다.'} <Link href="/input/review">분석 내용 확인·수정 →</Link></div>}
   {data.status === 'error' && <p role="alert">분석을 완료하지 못했습니다. {data.errors.find(e => e.message)?.message || '잠시 후 다시 시도해 주세요.'}</p>}
   {data.status === 'no_jobs' && <p role="status">현재 검색어로 분석할 수 있는 관련 공고가 없습니다.</p>}
   {data.status === 'needs_clarification' && <p role="status">{data.clarification_message} 기존 입력 수정 화면에서 목표나 희망 직무를 구체화해 주세요.</p>}
   {['success', 'partial'].includes(data.status) && !data.skills.length && <p role="status">분석한 공고에서 원문으로 확인할 수 있는 기술을 찾지 못했습니다.</p>}
   <ul className="skill-list">{data.skills.map(skill => <li key={skill.name} className="skill-card">
    <div className="skill-title"><h3>{skill.name}</h3><span className="badge">{categoryLabels[skill.category] || skill.category}</span></div>
    <p><b>{skill.mentioned_job_count} / {summary.analyzed_jobs}개 공고</b>에서 언급 · {(skill.mention_frequency * 100).toFixed(0)}%</p>
    <p className="skill-counts">필수 {skill.required_job_count} · 우대 {skill.preferred_job_count} · 단순 언급 {skill.mentioned_only_job_count} · 판단 불가 {skill.unknown_job_count}</p>
    <p className="field-help">직접 관련 {skill.direct_job_count} · 연관 직무 {skill.related_job_count} · {Object.entries(skill.seniority_distribution).map(([level, count]) => `${levelLabels[level]} ${count}`).join(' · ')}</p>
    {data.comparison?.comparisons?.filter(c => c.skill_name === skill.name).map(c => <div className="project-comparison" key={c.skill_name}>
     <p><span className="badge">{statusLabels[c.student_status]}</span></p><p>{c.reason}</p>
     <p className="field-help">{c.preparation_candidate === 'consider_learning' ? '추가 학습을 검토할 후보입니다. 공고 빈도는 개인의 학습 우선순위를 의미하지 않습니다.' : c.preparation_candidate === 'experience_confirmed' ? '사용자가 확인한 프로젝트 경험을 근거와 함께 표시합니다.' : '추가 준비를 결정하기 전에 경험 여부를 먼저 확인해 주세요.'}</p>
     {c.project_evidence.map(item => <ProjectEvidence key={item.experience_id} item={item} requestId={data.request_id}/>)}
     {c.student_status !== 'confirmed_experience' && <div className="doc-actions experience-actions"><button disabled={saving} onClick={() => answerSkill(skill, 'no_experience')}>이 기술 경험 없어요</button><button disabled={saving} onClick={() => answerSkill(skill, 'unknown')}>잘 모르겠어요</button><Link href="/input/review" className="button">본인 경험 확인·수정</Link></div>}
    </div>)}
    <details><summary>{skill.name} 원문 근거 {skill.evidence.length}건</summary>
     <ul className="skill-evidence">{skill.evidence.map((e, i) => <li key={`${e.job_id}-${i}`}>
      <span className="badge">{requirementLabels[e.requirement_type]}</span>{' '}
      {e.source_url ? <a href={e.source_url} target="_blank" rel="noopener noreferrer">{e.title} · Himalayas ↗</a> : <span>{e.title} · 원문 링크 미확인</span>}
      <blockquote>{e.evidence_text}</blockquote>
     </li>)}</ul>
    </details>
   </li>)}</ul>
   <p className="field-help">빈도는 수집한 해외 원격근무 공고 중 분석에 성공한 표본의 언급 비율입니다. 국내 취업시장 전체의 요구 비율이나 학생의 필수 역량·학습 우선순위를 뜻하지 않습니다. 필수·우대는 명시된 원문 표현을 기준으로 구분합니다.</p>
  </>}
  <p className="field-help">공고 출처: <a href="https://himalayas.app" target="_blank" rel="noopener noreferrer">Himalayas</a></p>
  {(phase === 'error' || (data && ['error', 'partial'].includes(data.status))) && <button className="primary" onClick={() => { forceNext.current = true; setRetry(v => v + 1); }}>다시 분석</button>}
 </div>;
}

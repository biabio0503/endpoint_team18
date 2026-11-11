'use client';
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';
import ProjectEvidence, { answerLabels, scopeLabels } from './ProjectEvidence';

const exclusionLabels = { pending: '본문 추출 중', failed: '본문 추출 실패', needs_ocr: 'OCR 필요', partial_unconfirmed: '부분 추출 확인 필요', invalid_extraction: '유효한 추출 버전 없음', empty_text: '본문이 비어 있음' };

function ExperienceCard({ item, requestId, busy, save }) {
 const [editing, setEditing] = useState(false);
 const [correction, setCorrection] = useState(item.user_answer?.correction || { skill_name: item.skill_name, activity: item.activity, contribution_scope: item.contribution_scope, role: item.role, output: item.output });
 const change = (field, value) => setCorrection(old => ({ ...old, [field]: value }));
 return <li className="skill-card">
  <div className="skill-title"><h3>{item.skill_name}</h3><span className="badge">{scopeLabels[item.contribution_scope]}</span><span className="badge">{answerLabels[item.user_confirmation] || '미확인'}</span></div>
  <p>{item.activity}</p>
  <ProjectEvidence item={item} requestId={requestId}/>
  <div className="doc-actions experience-actions">
   <button disabled={busy} onClick={() => save(item, 'confirmed')}>맞아요</button>
   <button disabled={busy} onClick={() => setEditing(!editing)}>수정할게요</button>
   <button disabled={busy} onClick={() => save(item, 'unknown')}>잘 모르겠어요</button>
   <button disabled={busy} onClick={() => save(item, 'no_experience')}>이 기술 경험 없어요</button>
  </div>
  {editing && <form className="experience-correction" onSubmit={async e => { e.preventDefault(); if (await save(item, 'corrected', correction)) setEditing(false); }}>
   <p className="field-help">수정한 내용은 사용자 답변으로 별도 저장됩니다. 직접 수행한 경험이면 수행 범위를 개인으로 선택해 주세요.</p>
   <label className="field">기술명<input required maxLength={150} value={correction.skill_name} onChange={e => change('skill_name', e.target.value)}/></label>
   <label className="field">수행 내용<textarea required maxLength={1000} value={correction.activity} onChange={e => change('activity', e.target.value)}/></label>
   <label className="field">수행 범위<select value={correction.contribution_scope} onChange={e => change('contribution_scope', e.target.value)}><option value="personal">본인 직접 수행</option><option value="team">팀 수행</option><option value="unknown">수행 주체 미확인</option></select></label>
   <label className="field">본인 역할 (선택)<input maxLength={500} value={correction.role || ''} onChange={e => change('role', e.target.value || null)}/></label>
   <label className="field">결과물 (선택)<input maxLength={1000} value={correction.output || ''} onChange={e => change('output', e.target.value || null)}/></label>
   <button className="primary" disabled={busy}>수정 내용 저장</button>
  </form>}
 </li>;
}

export default function ProjectExperienceReview() {
 const [id, setId] = useState(null), [data, setData] = useState(null), [busy, setBusy] = useState(true), [message, setMessage] = useState('');
 const load = useCallback(async () => {
  setBusy(true); setMessage(''); setData(null);
  try {
   const rid = await resolvePlanId();
   if (!rid) throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.');
   const result = await apiRequest(`/roadmap-inputs/${encodeURIComponent(rid)}/project-experience-analysis`);
   if (await resolvePlanId() !== rid) throw new Error('선택한 계획이 변경되었습니다. 다시 불러와 주세요.');
   setId(rid); setData(result);
  } catch (e) { setMessage(e.message); }
  finally { setBusy(false); }
 }, []);
 useEffect(() => { load(); }, [load]);
 async function mutate(path, body, method) {
  setBusy(true); setMessage('');
  try {
   if (await resolvePlanId() !== id) throw new Error('선택한 계획이 변경되었습니다. 다시 불러와 주세요.');
   const result = await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}${path}`, { method, body: JSON.stringify({ expected_input_revision: data.input_revision, ...body }) });
   if (await resolvePlanId() !== id) throw new Error('선택한 계획이 변경되었습니다. 다시 불러와 주세요.');
   setData(result); return true;
  } catch (e) { setMessage(e.message); if ([401, 404, 409].includes(e.status)) setData(null); return false; }
  finally { setBusy(false); }
 }
 const save = (item, status, correction) => mutate(`/project-experiences/${item.experience_id}/confirmation`, { status, ...(correction ? { correction } : {}) }, 'PATCH');
 return <section className="wire-box" aria-busy={busy}>
  <h3>프로젝트 경험 분석 및 확인</h3>
  <p className="notice">‘프로젝트 경험 분석 실행’ 또는 ‘프로젝트 경험 재분석’을 누르면 현재 분석 가능한 문서의 추출 텍스트가 외부 Gemini 서비스에서 처리됩니다. 문서 식별자·추출 버전·본문·문단 위치를 전송하며, 원본 파일과 계정 인증 정보는 전송하지 않습니다. 본문에 포함된 개인정보도 전송될 수 있으므로 업로드 문서를 먼저 확인해 주세요.</p>
  <p>‘맞아요’는 해당 설명이 본인의 수행 경험이라는 확인입니다. 팀 전체의 기술 사용과 본인의 직접 수행을 구분해 주세요.</p>
  {busy && <p role="status">문서 분석 또는 확인 내용을 처리하고 있습니다…</p>}
  {message && <p role="alert">{message}</p>}
  <div className="doc-actions"><button className="primary" disabled={busy || !data || !data.eligible_documents} onClick={() => mutate('/project-experience-analysis', {}, 'POST')}>프로젝트 경험 분석 실행</button><button disabled={busy} onClick={load}>최신 내용 불러오기</button><Link href="/input/documents" className="button">문서 확인</Link></div>
  {!!data?.analyzed_documents && <div className="doc-actions"><button disabled={busy} onClick={() => mutate('/project-experience-analysis', { refresh: true }, 'POST')}>프로젝트 경험 재분석</button><span className="field-help">저장된 본문으로 다시 분석하며 OCR은 다시 실행하지 않습니다. 새 카드의 사용자 확인·수정 답변은 다시 입력해 주세요.</span></div>}
  {data && <>
   <p className="field-help">입력 버전 {data.input_revision} · 분석 가능 {data.eligible_documents}개 · 분석 완료 {data.analyzed_documents}개 · 원문 검증 항목 {data.verified_experiences}개</p>
   {data.status === 'no_documents' && <p role="status">현재 분석 가능한 문서가 없습니다. 경험이 없다는 의미는 아닙니다. 문서 상태를 확인해 주세요.</p>}
   {data.status === 'not_started' && <p role="status">분석 실행 후 추출된 경험을 확인할 수 있습니다.</p>}
   {data.status === 'partial' && <p className="notice">일부 문서 또는 근거 검증이 완료되지 않았습니다. 검증된 항목만 표시합니다.</p>}
   {!!data.refresh_errors?.length && <p role="alert">재분석을 완료하지 못해 기존 분석 결과와 사용자 답변을 유지했습니다.</p>}
   {data.errors.length > 0 && <p role="alert">일부 분석을 완료하지 못했습니다. {data.errors.map(e => e.message || ({ document_too_long: '문서가 60,000자를 초과하여 분석하지 않았습니다.', evidence_not_in_source: '원문에 없는 근거를 제외했습니다.' }[e.code]) || '원문 검증을 통과하지 못한 항목이 있습니다.').filter((v, i, a) => a.indexOf(v) === i).join(' ')}</p>}
   {!!data.excluded_documents.length && <ul>{data.excluded_documents.map(d => <li key={d.document_id}>{d.original_filename}: {exclusionLabels[d.reason] || '본문 확인 필요'}</li>)}</ul>}
   {data.documents.filter(d => d.limitations.length).map(d => <p className="field-help" key={d.document_id}>{d.original_filename}: {d.limitations.join(' ')}</p>)}
   {data.status === 'success' && !data.experiences.length && <p>현재 문서에서 검증 가능한 기술 활동을 찾지 못했습니다. 경험 부재로 판단하지 않습니다.</p>}
   <ul className="skill-list">{data.experiences.map(item => <ExperienceCard key={item.experience_id} item={item} requestId={id} busy={busy} save={save}/>)}</ul>
  </>}
  <div className="result-link"><Link href="/result">다음: 결과 화면에서 직무 분석·로드맵 생성 →</Link></div>
 </section>;
}

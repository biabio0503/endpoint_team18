'use client';
import { useState } from 'react';
import { apiRequest } from '../../lib/api/client';

export const scopeLabels = { personal: '문서상 개인 수행', team: '팀 수행', unknown: '수행 주체 미확인' };
export const answerLabels = { confirmed: '본인 경험으로 확인', corrected: '사용자가 수정', unknown: '판단 보류', no_experience: '경험 없다고 답변' };
export const statusLabels = { confirmed_experience: '확인된 경험', document_supported: '문서 근거 있음 · 사용자 미확인', needs_confirmation: '경험 확인 필요', not_verified: '자료에서 확인되지 않음', no_experience: '경험 없다고 답변' };

export default function ProjectEvidence({ item, requestId }) {
 const [source, setSource] = useState(null), [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
 async function openSource() {
  setBusy(true); setMessage(''); setSource(null);
  try {
   const data = await apiRequest(`/roadmap-inputs/${encodeURIComponent(requestId)}/documents/${encodeURIComponent(item.document_id)}/extractions/${item.extraction_revision}`);
   if (!data.is_current_revision) throw new Error('문서 버전이 변경되었습니다. 분석 내용을 다시 불러와 주세요.');
   setSource(data.extracted_text);
  } catch (e) { setMessage(e.message); }
  finally { setBusy(false); }
 }
 return <details className="project-evidence"><summary>프로젝트 근거 · {item.original_filename} · 추출 버전 {item.extraction_revision}</summary>
  <p className="field-help">문서 원문 · {item.locations.map((l, i) => `${l.page ? `${l.page}페이지` : l.paragraph ? `${l.paragraph}문단` : `구간 ${i + 1}`}`).join(', ') || '위치 정보 없음'} · 문자 {item.evidence_start}–{item.evidence_end} (끝 제외)</p>
  {item.analyzed_input_revision !== undefined && <p className="field-help">프로젝트 분석 당시 입력 버전 {item.analyzed_input_revision}</p>}
  <blockquote className="source-text">{item.evidence_text}</blockquote>
  <p>AI 해석: {item.activity} · {scopeLabels[item.contribution_scope]}{item.role ? ` · 역할: ${item.role}` : ''}{item.output ? ` · 결과물: ${item.output}` : ''}</p>
  {!!item.contribution_basis?.context?.length && <details><summary>수행 주체 판정 문맥 · 실제 인용과 별도</summary>
   <p className="field-help">같은 표의 행 또는 직접 수행 목록에서 확인한 문서 근거입니다. 사용자의 ‘맞아요’ 답변과는 별도입니다.</p>
   {item.contribution_basis.context.map((context, i) => <div key={i}><blockquote className="source-text">{context.text}</blockquote><p className="field-help">{context.locations.map(l => l.page ? `${l.page}페이지` : l.paragraph ? `${l.paragraph}문단` : '위치 미확인').join(', ')} · 문자 {context.start}–{context.end} (끝 제외)</p></div>)}
  </details>}
  <p>사용자 답변: {answerLabels[item.user_confirmation] || '미확인'}</p>
  {item.user_answer?.correction && <div className="notice">사용자 수정 (문서 원문과 별도): {item.user_answer.correction.skill_name} · {item.user_answer.correction.activity} · {scopeLabels[item.user_answer.correction.contribution_scope]}{item.user_answer.correction.role ? ` · 역할: ${item.user_answer.correction.role}` : ''}{item.user_answer.correction.output ? ` · 결과물: ${item.user_answer.correction.output}` : ''}</div>}
  <button type="button" disabled={busy} onClick={openSource}>현재 문서 본문 확인</button>
  {message && <p role="alert">{message}</p>}
  {source !== null && <div className="source-text">{source}</div>}
 </details>;
}

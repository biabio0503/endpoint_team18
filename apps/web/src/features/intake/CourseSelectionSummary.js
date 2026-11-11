'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiRequest } from '../../lib/api/client';
import { resolvePlanId } from '../../lib/api/session';

export function SelectedCoursesSummary({ data }) {
 return <>
  <p><strong>{data.selection_summary.count}개 과목</strong></p>
  <p>알려진 학점 합계 <strong>{data.selection_summary.known_credits}</strong>학점<br/>학점 미확인 과목 {data.selection_summary.unknown_credits_count}개</p>
  <p className="field-help">현재 목록의 선택 합계이며 공식 총 취득학점이 아닙니다.</p>
  <ul>{data.selected_courses.length ? data.selected_courses.map(c => <li key={c.course_id}>{c.course_name} ({c.course_code || '코드 없음'})</li>) : <li>선택한 이수 과목 없음</li>}</ul>
 </>;
}

export default function CourseSelectionSummary() {
 const [data, setData] = useState(null), [message, setMessage] = useState('이수 선택을 불러오는 중입니다.');
 const [reload, setReload] = useState(0);
 useEffect(() => {
  let active = true;
  setData(null); setMessage('이수 선택을 불러오는 중입니다.');
  (async () => {
   try {
    const id = await resolvePlanId();
    if (!id) throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.');
    const plan = await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}`);
    if (!plan.input.catalog_id) throw new Error('현재 선택한 과목 목록이 없습니다.');
    const query = new URLSearchParams({ catalog_id: plan.input.catalog_id, page_size: '1' });
    // The summary always covers the whole catalog, independent of page size.
    const result = await apiRequest(`/roadmap-inputs/${encodeURIComponent(id)}/courses?${query}`);
    if (await resolvePlanId() !== id) throw new Error('선택한 계획이 변경되었습니다. 다시 불러와 주세요.');
    if (active) { setData(result); setMessage(''); }
   } catch (error) { if (active) setMessage(error.message); }
  })();
  return () => { active = false; };
 }, [reload]);
 return <section className="wire-box" aria-label="이수 과목 확인">
  <h3>이수 과목 확인</h3>
  {data && <SelectedCoursesSummary data={data}/>}
  {message && <p role="status">{message}</p>}
  <div className="doc-actions"><Link href="/input/courses">이수 선택 수정</Link><button onClick={() => setReload(n => n + 1)}>이수 선택 새로고침</button></div>
 </section>;
}

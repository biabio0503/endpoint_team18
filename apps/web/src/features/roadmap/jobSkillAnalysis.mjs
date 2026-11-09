// Tab visits/focus/reload only read saved evidence. Paid work requires run:true.
export function createJobSkillLoader({ apiRequest, resolvePlanId }) {
 const pending = new Map();
 const conflict = () => Object.assign(new Error('분석 중 입력이 변경되었습니다. 최신 내용을 불러와 주세요.'), { status: 409 });
 return async function load({ run = false, force = false } = {}) {
  const id = await resolvePlanId();
  if (!id) throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.');
  const path = `/roadmap-inputs/${encodeURIComponent(id)}`;
  const plan = await apiRequest(path);
  const key = `${id}:${plan.input_revision}:${run || force}`;
  if (!pending.has(key)) {
   pending.set(key, (async () => {
    const data = run || force ? await apiRequest(`${path}/job-skill-analysis`, { method: 'POST', body: JSON.stringify({ refresh: force }) }) : null;
    const comparison = await apiRequest(`${path}/skill-comparison`);
    const current = await apiRequest(path);
    if (await resolvePlanId() !== id || current.input_revision !== plan.input_revision || (data && data.input_revision !== current.input_revision) || comparison.input_revision !== current.input_revision) throw conflict();
    const jobs = data || comparison.job_analysis || { status: 'not_started' };
    return { keyword_details: [], collection_summary: { selected_jobs: 0 }, analysis_summary: { analyzed_jobs: 0, failed_jobs: 0, skipped_jobs: 0 }, skills: [], errors: [],
     ...jobs, input_revision: current.input_revision, comparison, request_id: id };
   })().finally(() => pending.delete(key)));
  }
  return pending.get(key);
 };
}

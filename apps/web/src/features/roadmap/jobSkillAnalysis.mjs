// Jobs persist on the server. Answers and newly completed analysis are read fresh.
export function createJobSkillLoader({ apiRequest, resolvePlanId }) {
 let cached = null;
 const pending = new Map();
 const conflict = () => Object.assign(new Error('분석 중 입력이 변경되었습니다. 다시 분석해 주세요.'), { status: 409 });
 return async function load({ force = false } = {}) {
  const id = await resolvePlanId();
  if (!id) { cached = null; throw new Error('계획이 없습니다. 기본 정보를 먼저 입력해 주세요.'); }
  const path = `/roadmap-inputs/${encodeURIComponent(id)}`;
  const plan = await apiRequest(path);
  const key = `${id}:${plan.input_revision}`;
  if (!force && cached?.key === key) {
   const comparison = await apiRequest(`${path}/skill-comparison`);
   if (await resolvePlanId() !== id || comparison.input_revision !== plan.input_revision) { cached = null; throw conflict(); }
   const jobs = comparison.job_analysis?.snapshot_id ? comparison.job_analysis : cached.data;
   cached = { key, data: { ...jobs, comparison, request_id: id } };
   return cached.data;
  }
  cached = null;
  if (!pending.has(key)) {
   const request = (async () => {
    const data = await apiRequest(`${path}/job-skill-analysis`, { method: 'POST', body: force ? '{"refresh":true}' : '{}' });
    const comparison = await apiRequest(`${path}/skill-comparison`);
    const current = await apiRequest(path);
    if (await resolvePlanId() !== id || current.input_revision !== plan.input_revision || data.input_revision !== current.input_revision || comparison.input_revision !== current.input_revision) throw conflict();
    const combined = { ...data, comparison, request_id: id };
    cached = { key, data: combined };
    return combined;
   })().finally(() => pending.delete(key));
   pending.set(key, request);
  }
  return pending.get(key);
 };
}

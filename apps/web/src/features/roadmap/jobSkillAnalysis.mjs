// Page-local cache only. Every reuse checks the server's complete input revision.
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
  if (!force && cached?.key === key) return cached.data;
  cached = null;
  if (!pending.has(key)) {
   const request = (async () => {
    const data = await apiRequest(`${path}/job-skill-analysis`, { method: 'POST', body: '{}' });
    const current = await apiRequest(path);
    if (await resolvePlanId() !== id || current.input_revision !== plan.input_revision || data.input_revision !== current.input_revision) throw conflict();
    cached = { key, data };
    return data;
   })().finally(() => pending.delete(key));
   pending.set(key, request);
  }
  return pending.get(key);
 };
}

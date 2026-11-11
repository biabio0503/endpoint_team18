// Component-local cache: never persists personalized responses across sessions.
export function createActivityLoader({ apiRequest, resolvePlanId, now = Date.now }) {
 let cached = null;
 const pending = new Map();
 return async function load({ refresh = false } = {}) {
  const id = await resolvePlanId();
  if (!id) throw new Error('계획이 없습니다. 진로 목표를 먼저 입력해 주세요.');
  const base = `/roadmap-inputs/${encodeURIComponent(id)}`;
  // Independent of Result's roadmap requests; failed/generated roadmaps are irrelevant.
  const plan = await apiRequest(base);
  const key = `${id}:${plan.input_revision}`;
  if (!refresh && cached?.key === key && now() < cached.expires) return cached.data;
  if (pending.has(key)) return pending.get(key);
  const request = apiRequest(`${base}/activities`).then(data => {
   const expiry = Date.parse(data.valid_until);
   cached = { key, data, expires: Number.isFinite(expiry) ? Math.min(expiry, now() + 300000) : now() };
   return data;
  }).catch(error => { cached = null; throw error; }).finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
 };
}

export const activityKindLabel = kind => kind === 'competition' ? '공모전' : '대외활동';

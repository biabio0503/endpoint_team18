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
  // Analysis refreshes can replace confirmations without changing input_revision.
  // This fingerprint covers only the evidence used by activity recommendations.
  const key = `${id}:${plan.activity_basis ?? plan.input_revision}`;
  if (!refresh && cached?.key === key && now() < cached.expires) return { ...cached.data, input_revision: plan.input_revision };
  if (pending.has(key)) return pending.get(key);
  const request = apiRequest(`${base}/activities`).then(data => {
   const expiry = Date.parse(data.valid_until);
   const responseKey = `${id}:${data.activity_basis ?? plan.activity_basis ?? plan.input_revision}`;
   cached = { key: responseKey, data, expires: Number.isFinite(expiry) ? Math.min(expiry, now() + 300000) : now() };
   return data;
  }).catch(error => { cached = null; throw error; }).finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
 };
}

export const activityKindLabel = kind => kind === 'competition' ? '공모전' : '대외활동';

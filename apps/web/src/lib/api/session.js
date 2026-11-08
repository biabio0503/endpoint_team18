import { apiRequest } from './client';
import { authClient } from './auth';

const PLAN_KEY = 'roadmap_request_id';
const OWNER_KEY = 'roadmap_request_owner';

export function clearSelectedPlan() {
  sessionStorage.removeItem(PLAN_KEY);
  sessionStorage.removeItem(OWNER_KEY);
}

async function currentUserId() {
  const { data, error } = await authClient().auth.getSession();
  if (error || !data.session?.user?.id) {
    clearSelectedPlan();
    throw new Error('인증 세션을 확인할 수 없습니다. 다시 로그인해 주세요.');
  }
  return data.session.user.id;
}

// Selection is scoped to this browser tab and the authenticated user.
export async function selectPlan(requestId, expectedUserId) {
  const userId = await currentUserId();
  if (userId !== expectedUserId) {
    clearSelectedPlan();
    throw new Error('로그인한 사용자가 변경되었습니다. 다시 시도해 주세요.');
  }
  sessionStorage.setItem(PLAN_KEY, requestId);
  sessionStorage.setItem(OWNER_KEY, userId);
}

export async function readResume(userId) {
  const result = await apiRequest('/roadmap-inputs/resume', { expectedUserId: userId });
  if (typeof result.found !== 'boolean' || (result.found && (typeof result.request?.request_id !== 'string' || !result.request.request_id))) {
    throw new Error('계획 응답을 확인할 수 없습니다. 다시 시도해 주세요.');
  }
  return result;
}

export async function resolvePlanId() {
  const userId = await currentUserId();
  const selected = sessionStorage.getItem(PLAN_KEY);
  if (selected && sessionStorage.getItem(OWNER_KEY) === userId) return selected;
  clearSelectedPlan();
  const latest = await readResume(userId);
  if (!latest.found) return null;
  await selectPlan(latest.request.request_id, userId);
  return latest.request.request_id;
}

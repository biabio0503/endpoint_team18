import { apiRequest } from './client';

// Always resolve against the authenticated owner; a stale tab must never select another account's plan.
export async function resolvePlanId() {
  const latest = await apiRequest('/roadmap-inputs/resume');
  return latest.found ? latest.request.request_id : null;
}

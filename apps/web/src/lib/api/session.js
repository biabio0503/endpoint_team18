import { apiRequest } from './client';

// Reuse the current tab's plan, or restore the latest plan from the session cookie.
export async function resolvePlanId() {
  let id = sessionStorage.getItem('roadmap_request_id');
  if (!id) {
    const latest = await apiRequest('/roadmap-inputs/resume');
    if (!latest.found) return null;
    id = latest.request.request_id;
    sessionStorage.setItem('roadmap_request_id', id);
  }
  return id;
}

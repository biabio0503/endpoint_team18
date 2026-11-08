export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.name = 'ApiError'; this.status = status; this.code = code; }
}
export async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, { ...options, cache: 'no-store', headers: { Accept: 'application/json', ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  } catch { throw new ApiError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.', 0); }
  let data;
  try { data = await response.json(); } catch { throw new ApiError('서버 응답을 확인할 수 없습니다.', response.status); }
  if (!response.ok) throw new ApiError(data.message || '요청을 처리하지 못했습니다.', response.status, data.error);
  return data;
}

import { createClient } from '@supabase/supabase-js';

let client;
export function authClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error('로그인 설정이 준비되지 않았습니다. 관리자에게 문의해 주세요.');
  if (!client) client = createClient(url, key);
  return client;
}

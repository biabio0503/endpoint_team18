import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

async function setup() {
 const storage = new Map();
 const sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
 let user = 'user-a', latest = { found: false, request: null }, calls = [];
 const context = vm.createContext({ sessionStorage });
 const session = new vm.SourceTextModule(await readFile(new URL('../../src/lib/api/session.js', import.meta.url), 'utf8'), { context });
 const auth = new vm.SyntheticModule(['authClient'], function () {
  this.setExport('authClient', () => ({ auth: { getSession: async () => ({ data: { session: user ? { user: { id: user } } : null }, error: null }) } }));
 }, { context });
 const client = new vm.SyntheticModule(['apiRequest'], function () {
  this.setExport('apiRequest', async (path, options) => { calls.push([path, options]); if (latest instanceof Error) throw latest; return latest; });
 }, { context });
 await session.link(specifier => specifier === './auth' ? auth : client);
 await session.evaluate();
 return { ...session.namespace, storage, calls, setUser: value => { user = value; }, setLatest: value => { latest = value; } };
}

test('selected plan remains selected even when another plan is the latest', async () => {
 const s = await setup();
 s.setLatest({ found: true, request: { request_id: 'older' } });
 await s.selectPlan('new', 'user-a');
 assert.equal(await s.resolvePlanId(), 'new');
 assert.equal(s.calls.length, 0);
});

test('selection is scoped to the authenticated user and the tab', async () => {
 const s = await setup();
 await s.selectPlan('user-a-plan', 'user-a');
 s.setUser('user-b');
 s.setLatest({ found: true, request: { request_id: 'user-b-plan' } });
 assert.equal(await s.resolvePlanId(), 'user-b-plan');
 assert.equal(s.storage.get('roadmap_request_owner'), 'user-b');
 assert.equal(s.calls[0][1].expectedUserId, 'user-b');
 s.setUser(null);
 await assert.rejects(s.resolvePlanId());
 assert.equal(s.storage.size, 0);
});

test('session change while selecting cannot retain a previous user plan', async () => {
 const s = await setup();
 await s.selectPlan('old', 'user-a');
 s.setUser('user-b');
 await assert.rejects(s.selectPlan('new', 'user-a'));
 assert.equal(s.storage.size, 0);
});

test('missing, failed, and malformed resume responses stay distinct', async () => {
 const s = await setup();
 assert.equal(await s.resolvePlanId(), null);
 s.setLatest(new Error('offline'));
 await assert.rejects(s.resolvePlanId(), /offline/);
 s.setLatest({});
 await assert.rejects(s.resolvePlanId(), /계획 응답/);
 s.setLatest({ found: true, request: null });
 await assert.rejects(s.resolvePlanId(), /계획 응답/);
});

test('authenticated requests use the intended user token and reject account changes', async () => {
 let user = 'user-a';
 const calls = [];
 const context = vm.createContext({ FormData, fetch: async (...args) => { calls.push(args); return { ok: true, json: async () => ({ found: false }) }; } });
 const module = new vm.SourceTextModule(await readFile(new URL('../../src/lib/api/client.js', import.meta.url), 'utf8'), { context });
 const auth = new vm.SyntheticModule(['authClient'], function () {
  this.setExport('authClient', () => ({ auth: { getSession: async () => ({ data: { session: { user: { id: user }, access_token: 'token-a' } }, error: null }) } }));
 }, { context });
 await module.link(() => auth);
 await module.evaluate();
 await module.namespace.apiRequest('/roadmap-inputs/resume', { expectedUserId: 'user-a' });
 assert.equal(calls[0][1].headers.Authorization, 'Bearer token-a');
 assert.equal(calls[0][1].expectedUserId, undefined);
 user = 'user-b';
 await assert.rejects(module.namespace.apiRequest('/roadmap-inputs', { method: 'POST', expectedUserId: 'user-a' }));
 assert.equal(calls.length, 1);
});

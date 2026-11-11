import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createActivityLoader } from '../../src/features/roadmap/activityLoader.mjs';

function setup() {
 let id = 'plan-a', revision = 1, basis = 'profile-1', clock = Date.parse('2026-11-12T14:59:00Z'), error = null;
 const calls = [];
 const apiRequest = async path => {
  calls.push(path);
  if (path.endsWith('/activities')) {
   if (error) throw error;
   return { request_id: id, input_revision: revision, activity_basis: basis, activities: [], valid_until: '2026-11-12T14:59:59.999Z' };
  }
  return { input_revision: revision, activity_basis: basis };
 };
 return { load: createActivityLoader({ apiRequest, resolvePlanId: async () => id, now: () => clock }), calls,
  setId: value => { id = value; }, setRevision: value => { revision = value; basis = 'profile-' + value; },
  setBasis: value => { basis = value; },
  setTime: value => { clock = Date.parse(value); }, setError: value => { error = value; } };
}

test('reanalysis with unchanged input revision invalidates only when recommendation evidence changes', async () => {
 const s = setup();
 const initial = await s.load();
 s.setBasis('project-without-confirmation');
 assert.notEqual((await s.load()).activity_basis, initial.activity_basis);
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 2);
 // Failed refresh preserves the profile; successful equivalent analysis does too.
 await s.load(); await s.load();
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 2);
 s.setBasis('job-without-gap');
 assert.equal((await s.load()).activity_basis, 'job-without-gap');
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 3);
});

test('tab/focus reuse activity response without depending on any roadmap endpoint', async () => {
 const s = setup();
 await s.load(); await s.load(); await s.load();
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 1);
 assert.ok(s.calls.every(path => !/\/roadmaps?$/.test(path)));
});

test('unrelated input revision updates the displayed revision without refetching activities', async () => {
 const s = setup(); const first = await s.load();
 s.setRevision(2); s.setBasis(first.activity_basis);
 assert.equal((await s.load()).input_revision, 2);
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 1);
});

test('input changes, selected plan changes and Korean midnight invalidate the cache', async () => {
 const s = setup();
 await s.load();
 s.setRevision(2); assert.equal((await s.load()).input_revision, 2);
 s.setId('plan-b'); assert.equal((await s.load()).request_id, 'plan-b');
 s.setTime('2026-11-12T15:00:00Z'); await s.load();
 assert.equal(s.calls.filter(path => path.endsWith('/activities')).length, 4);
});

test('manual retry refreshes and failure does not return stale personalized cards', async () => {
 const s = setup(); await s.load();
 s.setError(new Error('provider unavailable'));
 await assert.rejects(s.load({ refresh: true }), /provider unavailable/);
 await assert.rejects(s.load(), /provider unavailable/);
 s.setError(null); assert.equal((await s.load()).activities.length, 0);
 s.setId(null); await assert.rejects(s.load(), /진로 목표/);
});

test('overlapping tab activations share the same in-flight request', async () => {
 let calls = 0, release;
 const pending = new Promise(resolve => { release = resolve; });
 const load = createActivityLoader({ resolvePlanId: async () => 'plan', apiRequest: async path => {
  if (!path.endsWith('/activities')) return { input_revision: 1 };
  calls++; return pending;
 } });
 const a = load(), b = load();
 await new Promise(resolve => setImmediate(resolve));
 assert.equal(calls, 1);
 release({ activities: [], valid_until: '2026-11-12T00:00:00Z' });
 assert.deepEqual(await a, await b);
});

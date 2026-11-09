import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createJobSkillLoader } from '../../src/features/roadmap/jobSkillAnalysis.mjs';

function setup() {
 let revision = 1, id = 'plan-a', posts = 0, wait = null, error = null;
 const load = createJobSkillLoader({
  resolvePlanId: async () => id,
  apiRequest: async (path, options) => {
   if (options?.method === 'POST') {
    posts++;
    const input_revision = revision;
    if (wait) await wait;
    if (error) throw error;
    return { input_revision, status: 'success', skills: [] };
   }
   return { input_revision: revision };
  },
 });
 return { load, posts: () => posts, setRevision: value => { revision = value; }, setId: value => { id = value; },
  setWait: value => { wait = value; }, setError: value => { error = value; } };
}

test('same plan and revision reuses result across tab visits', async () => {
 const s = setup();
 const first = await s.load();
 assert.equal(await s.load(), first);
 assert.equal(s.posts(), 1);
 s.setRevision(2);
 assert.equal((await s.load()).input_revision, 2);
 assert.equal(s.posts(), 2);
 s.setId('plan-b');
 await s.load();
 assert.equal(s.posts(), 3);
});

test('concurrent renders deduplicate expensive POST requests', async () => {
 const s = setup();
 await Promise.all([s.load(), s.load(), s.load()]);
 assert.equal(s.posts(), 1);
 await s.load({ force: true });
 assert.equal(s.posts(), 2);
});

test('changed input or selected plan while analysis runs rejects stale results', async () => {
 for (const change of [s => s.setRevision(2), s => s.setId('plan-b')]) {
  const s = setup();
  let finish;
  s.setWait(new Promise(resolve => { finish = resolve; }));
  const pending = s.load();
  await new Promise(resolve => setImmediate(resolve));
  change(s);
  finish();
  await assert.rejects(pending, error => error.status === 409);
  s.setWait(null);
  await s.load();
  assert.equal(s.posts(), 2);
 }
});

test('failed request can retry and absence of a plan never starts analysis', async () => {
 const s = setup();
 s.setError(new Error('offline'));
 await assert.rejects(s.load(), /offline/);
 s.setError(null);
 await s.load();
 assert.equal(s.posts(), 2);
 s.setId(null);
 await assert.rejects(s.load(), /계획이 없습니다/);
 assert.equal(s.posts(), 2);
});

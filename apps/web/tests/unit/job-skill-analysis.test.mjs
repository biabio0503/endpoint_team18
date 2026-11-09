import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createJobSkillLoader, orderedSkills, recommendationScope } from '../../src/features/roadmap/jobSkillAnalysis.mjs';

function setup() {
 let revision = 1, id = 'plan-a', posts = 0, wait = null, error = null, saved = null;
 const bodies = [];
 const load = createJobSkillLoader({
  resolvePlanId: async () => id,
  apiRequest: async (path, options) => {
   if (options?.method === 'POST') {
    posts++; bodies.push(JSON.parse(options.body));
    const input_revision = revision;
    if (wait) await wait;
    if (error) throw error;
    saved = { input_revision, snapshot_id: 'snapshot', status: 'success', skills: [] };
    return saved;
   }
   return { input_revision: revision, job_analysis: saved || { status: 'not_started', skills: [] } };
  },
 });
 return { load, bodies, posts: () => posts, setRevision: value => { revision = value; }, setId: value => { id = value; },
  setWait: value => { wait = value; }, setError: value => { error = value; } };
}

test('tab visits, focus, new input and selected plan changes never call AI', async () => {
 const s = setup();
 assert.equal((await s.load()).status, 'not_started');
 await s.load(); s.setRevision(2); await s.load(); s.setId('plan-b'); await s.load();
 assert.equal(s.posts(), 0);
});

test('explicit concurrent runs deduplicate and saved reads are free', async () => {
 const s = setup();
 await Promise.all([s.load({ run: true }), s.load({ run: true }), s.load({ run: true })]);
 assert.equal(s.posts(), 1);
 assert.equal((await s.load()).snapshot_id, 'snapshot');
 assert.equal(s.posts(), 1);
 await s.load({ run: true, force: true });
 assert.deepEqual(s.bodies, [{ refresh: false }, { refresh: true }]);
});

test('changed input or selected plan rejects in-flight analysis', async () => {
 for (const change of [s => s.setRevision(2), s => s.setId('plan-b')]) {
  const s = setup(); let finish;
  s.setWait(new Promise(resolve => { finish = resolve; }));
  const pending = s.load({ run: true });
  await new Promise(resolve => setImmediate(resolve)); change(s); finish();
  await assert.rejects(pending, error => error.status === 409);
  s.setWait(null); await s.load();
  assert.equal(s.posts(), 1);
 }
});

test('failed paid request needs another explicit action, missing plan never posts', async () => {
 const s = setup(); s.setError(new Error('offline'));
 await assert.rejects(s.load({ run: true }), /offline/);
 await s.load(); assert.equal(s.posts(), 1);
 s.setError(null); await s.load({ run: true }); assert.equal(s.posts(), 2);
 s.setId(null); await assert.rejects(s.load({ run: true }), /계획이 없습니다/);
 assert.equal(s.posts(), 2);
});

test('same revision reads newly completed project evidence without AI', async () => {
 let complete = false;
 const load = createJobSkillLoader({ resolvePlanId: async () => 'plan', apiRequest: async (path, options) => {
  assert.ok(!options?.method);
  if (path.endsWith('/skill-comparison')) return { input_revision: 1, project_analysis: { status: complete ? 'success' : 'not_started' } };
  return { input_revision: 1 };
 } });
 assert.equal((await load()).comparison.project_analysis.status, 'not_started');
 complete = true;
 assert.equal((await load()).comparison.project_analysis.status, 'success');
});

test('comparison display, actual model input and proposed activities remain distinct', () => {
 const result = { generation_scope: { included_skills: ['SQL', 'Python', 'Excel'] },
  roadmap: [{ related_skills: ['SQL'] }, { skill_targets: [{ skill_name: 'Python' }] }] };
 assert.deepEqual(recommendationScope(result, 'CAD'), { included: false, activities: 0 });
 assert.deepEqual(recommendationScope(result, 'Excel'), { included: true, activities: 0 });
 assert.deepEqual(recommendationScope(result, 'SQL'), { included: true, activities: 1 });
 assert.deepEqual(recommendationScope({ roadmap: [] }, 'SQL'), { included: null, activities: 0 });
});

test('new comparison order reflects server evidence/experience; legacy saved names stay intact', () => {
 const skills = [{ name: 'PowerBI' }, { name: 'Power BI' }, { name: 'SQL' }];
 const comparisons = [{ skill_name: 'SQL' }, { skill_name: 'Power BI' }];
 assert.deepEqual(orderedSkills({ skills, comparison: { comparisons } }), skills);
 assert.deepEqual(orderedSkills({ analysis_version: 'job-skills-v2', skills, comparison: { comparisons } }).map(s => s.name), ['SQL', 'Power BI', 'PowerBI']);
 assert.deepEqual(skills.map(s => s.name), ['PowerBI', 'Power BI', 'SQL']);
});

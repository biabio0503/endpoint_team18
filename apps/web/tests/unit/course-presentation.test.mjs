import assert from 'node:assert/strict';
import test from 'node:test';
import { coursePresentation, relatedCourseNames } from '../../src/features/roadmap/coursePresentation.mjs';

const ko = 'stcse-2026-ac66832f2c533c700dde1354';
const en = 'stcse-2026-56e5e2a1aedbfd4d2e87404c';
const name = '데이터베이스 (Database)';
const card = id => ({ course_id: id, course_name: name, member_course_ids: [ko, en], credits: 3 });

test('an old English ID and the Korean ID resolve to the same bilingual card', () => {
 const { cards, byId } = coursePresentation([card(en)]);
 assert.equal(cards.length, 1);
 assert.equal(cards[0].course_name, name);
 assert.equal(cards[0].credits, 3);
 assert.equal(byId.get(ko), byId.get(en));
 assert.deepEqual(relatedCourseNames([en], byId), [name]);
 assert.deepEqual(relatedCourseNames([ko], byId), [name]);
});

test('duplicate historical cards and both step references display once', () => {
 const original = [{ ...card(en), related_skills: ['SQL'], evidence_refs: ['en'] },
                   { ...card(ko), related_skills: ['Python'], evidence_refs: ['ko'] }];
 const before = structuredClone(original);
 const { cards, byId } = coursePresentation(original);
 assert.equal(cards.length, 1);
 assert.deepEqual(cards[0].related_skills, ['SQL', 'Python']);
 assert.deepEqual(cards[0].evidence_refs, ['en', 'ko']);
 assert.deepEqual(relatedCourseNames([en, ko], byId), [name]);
 assert.deepEqual(original, before);
});

test('similar or identical names without explicit member IDs stay separate', () => {
 const { cards } = coursePresentation([card(ko), { course_id: 'advanced', course_name: '고급 데이터베이스' },
                                       { course_id: 'other', course_name: name }]);
 assert.equal(cards.length, 3);
});

test('an unavailable historical reference does not crash the roadmap', () => {
 const { byId } = coursePresentation([card(ko)]);
 assert.deepEqual(relatedCourseNames(['missing', en], byId), [name]);
});

test('preserves all server-ranked cards in order beyond five', () => {
 const input = Array.from({ length: 6 }, (_, i) => ({ course_id: String(i), course_name: String(i) }));
 assert.deepEqual(coursePresentation(input).cards.map(c => c.course_id), input.map(c => c.course_id));
});

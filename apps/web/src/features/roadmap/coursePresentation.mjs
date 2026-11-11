// Identity comes only from the server's reviewed member IDs, never title matching.
export function coursePresentation(courses) {
 const grouped = new Map();
 for (const course of courses) {
  const members = course.member_course_ids?.length ? course.member_course_ids : [course.course_id];
  const id = members[0];
  const prior = grouped.get(id);
  grouped.set(id, {
   ...(prior || course), course_id: id,
   member_course_ids: [...new Set([...(prior?.member_course_ids || []), ...members, course.course_id])],
   related_skills: [...new Set([...(prior?.related_skills || []), ...(course.related_skills || [])])],
   evidence_refs: [...new Set([...(prior?.evidence_refs || []), ...(course.evidence_refs || [])])],
  });
 }
 const cards = [...grouped.values()];
 const byId = new Map(cards.flatMap(course => course.member_course_ids.map(id => [id, course])));
 return { cards, byId };
}

export function relatedCourseNames(ids, byId) {
 const courses = ids.map(id => byId.get(id)).filter(Boolean);
 return [...new Map(courses.map(course => [course.course_id, course.course_name])).values()];
}

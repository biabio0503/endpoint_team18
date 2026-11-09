"""Reference catalogs and request-scoped course selections."""
class CourseRepository:
    def __init__(self, db): self.db=db
    def universities(self): return [dict(r) for r in self.db.execute('SELECT university_id, university_name, is_supported FROM universities ORDER BY university_name, university_id')]
    def university(self, uid): return self.db.execute('SELECT * FROM universities WHERE university_id=?',(uid,)).fetchone()
    def departments(self, uid): return [dict(r) for r in self.db.execute('SELECT department_id, university_id, department_name, is_supported FROM departments WHERE university_id=? ORDER BY department_name, department_id',(uid,))]
    def department(self, did): return self.db.execute('SELECT * FROM departments WHERE department_id=?',(did,)).fetchone()
    def catalogs(self, did): return [dict(r) for r in self.db.execute('SELECT * FROM course_catalogs WHERE department_id=? AND is_selectable=TRUE ORDER BY version_label, catalog_id',(did,))]
    def catalog(self, cid): return self.db.execute('SELECT * FROM course_catalogs WHERE catalog_id=?',(cid,)).fetchone()
    def courses(self, rid, cid, include_description=False):
        hours = 'cc.theory_hours,cc.practice_hours' if getattr(self.db, 'backend', 'sqlite') == 'postgres' else 'NULL AS theory_hours,NULL AS practice_hours'
        description = ''
        if include_description:
            has_description = True
            if getattr(self.db, 'backend', 'sqlite') == 'postgres':
                has_description = bool(self.db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='catalog_courses' AND column_name='description_text'").fetchone())
            description = ',cc.description_text' if has_description else ',NULL AS description_text'
        return [dict(r) for r in self.db.execute('''SELECT cc.course_id,cc.course_name,cc.course_code,cc.credits,cc.category,cc.recommended_year,cc.recommended_term,''' + hours + description + ''',COALESCE(s.is_completed,FALSE) AS is_completed
          FROM catalog_courses cc LEFT JOIN input_course_states s ON s.request_id=? AND s.course_id=cc.course_id WHERE cc.catalog_id=? ORDER BY cc.course_name,cc.course_id''',(rid,cid))]
    def outside(self, rid, cid):
        return [dict(r) for r in self.db.execute('''SELECT s.course_id, s.source_catalog_id, cc.course_name, cc.course_code, cc.credits FROM input_course_states s JOIN catalog_courses cc ON cc.catalog_id=s.source_catalog_id AND cc.course_id=s.course_id WHERE s.request_id=? AND s.is_completed=TRUE AND NOT EXISTS (SELECT 1 FROM catalog_courses current WHERE current.catalog_id=? AND current.course_id=s.course_id) ORDER BY cc.course_name,s.course_id''',(rid,cid))]
    def recommendation_courses(self, rid, cid):
        courses = self.courses(rid, cid, include_description=True)
        completed = {r['course_id'] for r in self.db.execute('SELECT course_id FROM input_course_states WHERE request_id=? AND is_completed=TRUE', (rid,))}
        pairs = {}
        for row in self.db.execute('''SELECT e.course_id,e.equivalent_course_id FROM verified_course_equivalences e
            JOIN courses a ON a.course_id=e.course_id JOIN courses b ON b.course_id=e.equivalent_course_id
            WHERE a.university_id=b.university_id'''):
            a, b = row['course_id'], row['equivalent_course_id']
            pairs.setdefault(a, set()).add(b)
            pairs.setdefault(b, set()).add(a)
        for course in courses:
            # Direct, reviewed pairs only; substitution is not inferred transitively.
            equivalents = pairs.get(course['course_id'], set())
            course['verified_equivalent_ids'] = sorted(equivalents)
            course['equivalent_completed'] = bool(equivalents & completed)
        return courses
    def membership(self,cid,course): return self.db.execute('SELECT 1 FROM catalog_courses WHERE catalog_id=? AND course_id=?',(cid,course)).fetchone() is not None
    def state(self,rid,course): return self.db.execute('SELECT * FROM input_course_states WHERE request_id=? AND course_id=?',(rid,course)).fetchone()
    def save_state(self,rid,course,cid,completed,at):
        self.db.execute('''INSERT INTO input_course_states(request_id,course_id,source_catalog_id,is_completed,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(request_id,course_id) DO UPDATE SET source_catalog_id=excluded.source_catalog_id,is_completed=excluded.is_completed,updated_at=excluded.updated_at''',(rid,course,cid,bool(completed),at))
    def changed(self,rid,at):
        self.db.execute('''UPDATE roadmap_inputs SET input_revision=input_revision+1,course_selection_revision=course_selection_revision+1,reviewed_catalog_id=NULL,reviewed_selection_revision=NULL,reviewed_at=NULL,updated_at=? WHERE request_id=?''',(at,rid))
    def review(self,rid,cid,revision,missing,at):
        self.db.execute('''UPDATE roadmap_inputs SET reviewed_catalog_id=?,reviewed_selection_revision=?,reported_missing_courses=?,reviewed_at=?,input_revision=input_revision+1,updated_at=? WHERE request_id=?''',(cid,revision,bool(missing),at,at,rid))

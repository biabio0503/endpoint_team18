CREATE TRIGGER catalog_course_university_insert BEFORE INSERT ON catalog_courses
WHEN NOT EXISTS (
 SELECT 1 FROM course_catalogs cc JOIN departments d ON d.department_id=cc.department_id
 JOIN courses c ON c.course_id=NEW.course_id AND c.university_id=d.university_id
 WHERE cc.catalog_id=NEW.catalog_id
)
BEGIN SELECT RAISE(ABORT,'course and catalog must belong to the same university'); END;
CREATE TRIGGER catalog_course_university_update BEFORE UPDATE OF catalog_id,course_id ON catalog_courses
WHEN NOT EXISTS (
 SELECT 1 FROM course_catalogs cc JOIN departments d ON d.department_id=cc.department_id
 JOIN courses c ON c.course_id=NEW.course_id AND c.university_id=d.university_id
 WHERE cc.catalog_id=NEW.catalog_id
)
BEGIN SELECT RAISE(ABORT,'course and catalog must belong to the same university'); END;

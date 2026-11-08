"""Build model inputs and enforce the server-owned course scope."""
from services.gemini import recommend_ids


def recommend(profile, courses, review_status, call=recommend_ids):
    candidates = [c for c in courses if not c['is_completed']]
    if not candidates:
        return []
    fields = ('course_id', 'course_name', 'description_text', 'category', 'recommended_year', 'recommended_term')
    model_courses = [{field: c.get(field) for field in fields} for c in candidates]
    ids = call(profile, model_courses)
    allowed = {str(c['course_id']): c for c in candidates}
    result, seen = [], set()
    for course_id in ids:
        if course_id in allowed and course_id not in seen:
            course = dict(allowed[course_id])
            course.pop('description_text', None)
            course['is_completed'] = False
            course['completion_state'] = 'not_selected_in_reviewed_catalog' if review_status in ('confirmed', 'partial') else 'unconfirmed'
            result.append(course)
            seen.add(course_id)
            if len(result) == 5:
                break
    return result

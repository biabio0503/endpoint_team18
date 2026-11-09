"""Build model inputs and enforce the server-owned course scope."""
from services.gemini import recommend_ids


def available_courses(courses):
    return {str(c['course_id']): c for c in courses if not c['is_completed'] and not c.get('equivalent_completed')}


def selected_courses(ids, courses, review_status):
    """Shared catalog membership, completion, deduplication and maximum rules."""
    allowed = available_courses(courses)
    result, seen = [], set()
    for course_id in ids:
        if course_id in allowed and course_id not in seen and not set(allowed[course_id].get('verified_equivalent_ids', [])) & seen:
            course = dict(allowed[course_id])
            course.pop('description_text', None)
            course['is_completed'] = False
            course['completion_state'] = 'not_selected_in_reviewed_catalog' if review_status in ('confirmed', 'partial') else 'unconfirmed'
            result.append(course)
            seen.add(course_id)
            if len(result) == 5:
                break
    return result


def recommend(profile, courses, review_status, call=recommend_ids):
    candidates = list(available_courses(courses).values())
    if not candidates:
        return []
    fields = ('course_id', 'course_name', 'description_text', 'category', 'recommended_year', 'recommended_term')
    model_courses = [{field: c.get(field) for field in fields} for c in candidates]
    ids = call(profile, model_courses)
    return selected_courses(ids, courses, review_status)

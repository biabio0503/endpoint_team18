"""Strict model output and API requests; student facts remain server-owned."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=180)]
LocalId = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
StudentStatus = Literal['confirmed_experience', 'document_supported', 'needs_confirmation', 'not_verified', 'no_experience']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class GenerationRequest(StrictModel):
    expected_input_revision: int = Field(ge=0)
    refresh: bool = False


class ProgressRequest(StrictModel):
    is_completed: bool
    expected_progress_version: int = Field(ge=0)


class CourseSuggestion(StrictModel):
    course_id: Identifier = Field(description='Exact eligible_courses ID; exclude completed/equivalent courses and duplicate equivalents.')
    related_skills: list[Identifier] = Field(min_length=1, max_length=20, description='1-20 unique skill_name values from input skills only.')
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=40, description='Exactly the comparison_ref for each related skill; no job/experience refs.')
    course_evidence: Text = Field(description='Exact contiguous description_text quote, or exact course_name when description is absent. Never translate.')
    reason: Text
    personalization_reason: Text
    course_role: Literal['foundation', 'application', 'advanced']
    recommendation_confidence: Literal['supported', 'limited']


class SkillTarget(StrictModel):
    skill_name: Identifier = Field(description='Exact skill_name from input skills only.')
    student_status: StudentStatus = Field(description='Copy the input student_status for this skill exactly.')
    action_type: Literal['verify_experience', 'learn', 'deepen'] = Field(description='Copy allowed_action_type exactly; same action_type across this step.')


class RoadmapTask(StrictModel):
    task_id: LocalId
    task_type: Literal['verify_experience', 'practice', 'apply', 'validate', 'document'] = Field(description='One of the target skills allowed_task_types.')
    title: Text
    action: Text = Field(description='Concrete nonempty action, 1-1500 chars. For verify_experience include BOTH 경험 and 확인 in this field. No 교과목/강의/수강. Use only included skills, never out_of_scope_skill_names, even as a tool for an included skill.')
    completion_criteria: Text = Field(description='Nonempty observable completion criterion, 1-1500 chars; verification records whether evidence exists, not proof of mastery.')
    deliverable: Text = Field(description='Nonempty artifact to retain, 1-1500 chars; required also for verify_experience.')


class RoadmapStep(StrictModel):
    step_id: LocalId
    order: int = Field(ge=1, le=5, description='Contiguous order starting at 1, matching array position.')
    title: Text
    purpose: Text
    reason: Text
    skill_targets: list[SkillTarget] = Field(min_length=1, max_length=20)
    related_course_ids: list[Identifier] = Field(max_length=5, description='0-5 unique IDs from this output recommended_courses, sharing at least one target skill.')
    depends_on: list[LocalId] = Field(max_length=4, description='0-4 unique step_ids from earlier steps only; no cycles or task IDs.')
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=40, description='Exactly the comparison_ref for every skill_target; input allowed_evidence_refs only.')
    limitations: Text
    tasks: list[RoadmapTask] = Field(min_length=1, max_length=3, description='1-3 tasks; globally unique task_id and action; every field required.')


class GeneratedRoadmap(StrictModel):
    recommended_courses: list[CourseSuggestion] = Field(max_length=5, description='0-5 eligible, unique, non-equivalent courses.')
    roadmap: list[RoadmapStep] = Field(min_length=1, max_length=5, description='1-5 steps; globally unique step_id, contiguous order, no dates/durations.')

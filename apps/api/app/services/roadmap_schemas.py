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
    course_id: Identifier
    related_skills: list[Identifier] = Field(min_length=1, max_length=20)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=40)
    course_evidence: Text
    reason: Text
    personalization_reason: Text
    course_role: Literal['foundation', 'application', 'advanced']
    recommendation_confidence: Literal['supported', 'limited']


class SkillTarget(StrictModel):
    skill_name: Identifier
    student_status: StudentStatus
    action_type: Literal['verify_experience', 'learn', 'deepen']


class RoadmapTask(StrictModel):
    task_id: LocalId
    task_type: Literal['verify_experience', 'practice', 'apply', 'validate', 'document']
    title: Text
    action: Text
    completion_criteria: Text
    deliverable: Text


class RoadmapStep(StrictModel):
    step_id: LocalId
    order: int = Field(ge=1, le=5)
    title: Text
    purpose: Text
    reason: Text
    skill_targets: list[SkillTarget] = Field(min_length=1, max_length=20)
    related_course_ids: list[Identifier] = Field(max_length=5)
    depends_on: list[LocalId] = Field(max_length=4)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=40)
    limitations: Text
    tasks: list[RoadmapTask] = Field(min_length=1, max_length=3)


class GeneratedRoadmap(StrictModel):
    recommended_courses: list[CourseSuggestion] = Field(max_length=5)
    roadmap: list[RoadmapStep] = Field(min_length=1, max_length=5)

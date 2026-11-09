"""AI observations and user statements are deliberately separate contracts."""
from typing import Literal

from pydantic import Field, field_validator, model_validator
from services.job_skill_schemas import Category, StrictModel

Scope = Literal['personal', 'team', 'unknown']
AnswerStatus = Literal['confirmed', 'corrected', 'unknown', 'no_experience']


class Experience(StrictModel):
    skill_name: str = Field(min_length=1, max_length=150)
    category: Category
    activity: str = Field(min_length=1, max_length=1000)
    contribution_scope: Scope
    role: str | None = Field(default=None, max_length=500)
    output: str | None = Field(default=None, max_length=1000)
    evidence_text: str = Field(min_length=1, max_length=4000)

    @field_validator('skill_name', 'activity', 'evidence_text', 'role', 'output')
    @classmethod
    def non_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError('Text must not be blank')
        return value


class DocumentExperience(StrictModel):
    document_id: str = Field(min_length=1, max_length=100)
    extraction_revision: int = Field(ge=1)
    experiences: list[Experience] = Field(max_length=100)


class Correction(StrictModel):
    skill_name: str = Field(min_length=1, max_length=150)
    activity: str = Field(min_length=1, max_length=1000)
    contribution_scope: Scope
    role: str | None = Field(default=None, max_length=500)
    output: str | None = Field(default=None, max_length=1000)

    _non_blank = field_validator('skill_name', 'activity', 'role', 'output')(Experience.non_blank.__func__)


class ExperienceAnswer(StrictModel):
    expected_input_revision: int = Field(ge=0)
    status: AnswerStatus
    correction: Correction | None = None

    @model_validator(mode='after')
    def correction_required(self):
        if (self.status == 'corrected') != (self.correction is not None):
            raise ValueError('Only corrected answers require separate correction data')
        return self


class SkillAnswer(StrictModel):
    expected_input_revision: int = Field(ge=0)
    snapshot_id: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=150)
    status: Literal['unknown', 'no_experience']


class JobAnalysisRequest(StrictModel):
    refresh: bool = False

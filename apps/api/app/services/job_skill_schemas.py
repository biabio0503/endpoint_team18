"""Strict contracts for Gemini job analysis; no student documents or course data."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def english_role(value):
    value = ' '.join(value.split())
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 +./&'()-]{1,99}", value) or len(value.split()) > 8:
        raise ValueError('Expected a short English job title')
    return value


class SearchKeyword(StrictModel):
    keyword: str = Field(min_length=2, max_length=100)
    relation: Literal['direct', 'related']

    _role = field_validator('keyword')(english_role)


class RoleInterpretation(StrictModel):
    status: Literal['success', 'needs_clarification']
    canonical_role: str | None
    search_keywords: list[SearchKeyword] = Field(max_length=3)
    clarification_message: str | None

    @model_validator(mode='after')
    def check_role(self):
        if self.status == 'needs_clarification':
            if self.canonical_role is not None or self.search_keywords or not (self.clarification_message or '').strip():
                raise ValueError('Clarification must not include invented roles or keywords')
            return self
        if not self.canonical_role:
            raise ValueError('Canonical role is required')
        self.canonical_role = english_role(self.canonical_role)
        unique = {}
        for entry in self.search_keywords:
            key = entry.keyword.casefold()
            if key in unique and unique[key].relation != entry.relation:
                raise ValueError('Conflicting keyword relations')
            unique.setdefault(key, entry)
        self.search_keywords = list(unique.values())
        if not any(entry.relation == 'direct' for entry in self.search_keywords):
            raise ValueError('At least one direct keyword is required')
        return self


Category = Literal['programming_language', 'database_query_language', 'framework',
                   'database', 'cloud', 'devops', 'development_tool', 'data_ai',
                   'technical_competency', 'other']
Requirement = Literal['required', 'preferred', 'mentioned', 'unknown']


class ExtractedSkill(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    category: Category
    requirement_type: Requirement
    evidence_text: str = Field(min_length=1, max_length=4000)

    @field_validator('name', 'evidence_text')
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError('Blank text is not evidence')
        return value


class JobExtraction(StrictModel):
    job_id: str = Field(min_length=1)
    skills: list[ExtractedSkill] = Field(max_length=100)


class BatchExtraction(StrictModel):
    jobs: list[JobExtraction] = Field(max_length=5)

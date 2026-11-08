"""Explicit evidence contract; fields contain source words, never inferred skills."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Evidence:
    source_key: str
    kind: str
    url: str
    content_type: str
    raw: bytes
    title: str | None
    source_text: str
    segments: list
    facts: dict
    recruitment: dict
    status: str
    limitations: list
    parser_version: str
    observed_at: str | None = None

@dataclass(frozen=True)
class Batch:
    evidence: list
    failures: list
    discovered: int
    coverage: str

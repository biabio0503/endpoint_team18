"""Discovery result, including unsuccessful observations; never replace good data with errors."""
from dataclasses import dataclass, field


@dataclass
class Batch:
    items: list
    status: str = 'success'
    metrics: dict = field(default_factory=dict)

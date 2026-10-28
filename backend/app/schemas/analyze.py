from pydantic import BaseModel, Field
from typing import List, Optional


class EvidenceResponse(BaseModel):
    title: str
    url: str
    source: str
    score: float
    snippet: str
    quality_score: float


class AnalyzeRequest(BaseModel):
    urls: List[str]
    budget: Optional[float] = None
    budget_currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    requirements: Optional[str] = None
    save_history: bool = True
from pydantic import BaseModel
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
    requirements: Optional[str] = None
    save_history: bool = True
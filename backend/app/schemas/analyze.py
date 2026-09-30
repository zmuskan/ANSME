from pydantic import BaseModel
from typing import List, Optional

class AnalyzeRequest(BaseModel):
    urls: List[str]
    budget: Optional[float] = None
    requirements: Optional[str] = None
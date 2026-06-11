from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ReviewBase(BaseModel):
    review_text: str
    platform:    Optional[str] = "custom"
    author_name: Optional[str] = None
    rating:      Optional[float] = None
    review_url:  Optional[str] = None

class ReviewCreate(ReviewBase):
    pass

class ReviewOut(ReviewBase):
    id:             int
    language:       Optional[str]
    review_type:    Optional[str]
    priority_level: Optional[str]
    sentiment:      Optional[str]
    responded:      bool
    imported_at:    datetime

    class Config:
        from_attributes = True

class ResponseOut(BaseModel):
    id:                    int
    review_id:             int
    response_professional: Optional[str]
    response_friendly:     Optional[str]
    response_supportive:   Optional[str]
    selected_tone:         Optional[str]
    created_at:            datetime

    class Config:
        from_attributes = True

class ImportResult(BaseModel):
    imported:  int
    skipped:   int
    languages: List[str]
    message:   str

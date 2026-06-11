from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from config.database import Base

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(String, unique=True, nullable=False, default="default")
    name          = Column(String)
    email         = Column(String)
    business_name = Column(String)
    product_url   = Column(String)
    product_desc  = Column(Text)
    created_at    = Column(DateTime, default=func.now())
    reviews       = relationship("Review", back_populates="user")

class Review(Base):
    __tablename__ = "reviews"
    id             = Column(Integer, primary_key=True)
    user_id        = Column(String, ForeignKey("users.user_id"))
    platform       = Column(String)
    review_text    = Column(Text, nullable=False)
    author_name    = Column(String)
    rating         = Column(Float)
    review_url     = Column(String)
    language       = Column(String, default="en")
    review_type    = Column(String)
    priority_level = Column(String)
    sentiment      = Column(String)
    responded      = Column(Boolean, default=False)
    imported_at    = Column(DateTime, default=func.now())
    processed_at   = Column(DateTime)
    user           = relationship("User", back_populates="reviews")
    responses      = relationship("Response", back_populates="review")

class Response(Base):
    __tablename__ = "responses"
    id                    = Column(Integer, primary_key=True)
    review_id             = Column(Integer, ForeignKey("reviews.id"))
    user_id               = Column(String)
    response_professional = Column(Text)
    response_friendly     = Column(Text)
    response_supportive   = Column(Text)
    selected_response     = Column(Text)
    selected_tone         = Column(String)
    created_at            = Column(DateTime, default=func.now())
    review                = relationship("Review", back_populates="responses")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(String)
    category   = Column(String)
    title      = Column(String, nullable=False)
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())

class ResponseMemory(Base):
    __tablename__ = "response_memory"
    id                  = Column(Integer, primary_key=True)
    user_id             = Column(String)
    review_type         = Column(String)
    sentiment           = Column(String)
    review_keyword      = Column(String)
    successful_response = Column(Text)
    usage_count         = Column(Integer, default=0)
    created_at          = Column(DateTime, default=func.now())

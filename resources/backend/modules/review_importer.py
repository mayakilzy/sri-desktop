import pandas as pd
import io
from typing import List, Dict
from langdetect import detect, LangDetectException
from sqlalchemy.orm import Session
from core.models import Review, User
from datetime import datetime

SUPPORTED_PLATFORMS = ["appsumo", "gumroad", "etsy", "amazon", "custom"]

def detect_language(text):
    try:
        return detect(text)
    except LangDetectException:
        return "en"

def normalize_platform(platform):
    if not platform:
        return "custom"
    p = str(platform).lower().strip()
    for s in SUPPORTED_PLATFORMS:
        if s in p:
            return s
    return "custom"

def parse_csv(file_content):
    try:
        df = pd.read_csv(io.BytesIO(file_content))
    except Exception:
        df = pd.read_csv(io.BytesIO(file_content), encoding="latin-1")
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    column_map = {
        "review_text": ["review_text", "text", "review", "comment", "body", "content"],
        "author_name": ["author_name", "author", "name", "user", "username", "reviewer"],
        "rating":      ["rating", "stars", "score", "rate"],
        "platform":    ["platform", "source", "store", "channel"],
        "review_url":  ["review_url", "url", "link"],
    }
    mapped = {}
    for target, candidates in column_map.items():
        for candidate in candidates:
            if candidate in df.columns:
                mapped[target] = candidate
                break
    if "review_text" not in mapped:
        raise ValueError("No review text column found")
    reviews = []
    for _, row in df.iterrows():
        text = str(row[mapped["review_text"]]).strip()
        if not text or text == "nan":
            continue
        reviews.append({
            "review_text": text,
            "author_name": str(row[mapped["author_name"]]).strip() if "author_name" in mapped else None,
            "rating":      float(row[mapped["rating"]]) if "rating" in mapped else None,
            "platform":    normalize_platform(str(row[mapped["platform"]])) if "platform" in mapped else "custom",
            "review_url":  str(row[mapped["review_url"]]).strip() if "review_url" in mapped else None,
        })
    return reviews

def import_reviews(file_content, db, user_id="default", platform_override=None):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, name="Default User")
        db.add(user)
        db.commit()
    raw_reviews = parse_csv(file_content)
    imported = 0
    skipped = 0
    languages = set()
    for r in raw_reviews:
        existing = db.query(Review).filter(
            Review.user_id == user_id,
            Review.review_text == r["review_text"]
        ).first()
        if existing:
            skipped += 1
            continue
        lang = detect_language(r["review_text"])
        languages.add(lang)
        review = Review(
            user_id=user_id,
            platform=platform_override or r["platform"],
            review_text=r["review_text"],
            author_name=r["author_name"],
            rating=r["rating"],
            review_url=r["review_url"],
            language=lang,
        )
        db.add(review)
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped, "languages": list(languages),
            "message": f"Imported {imported} reviews in {len(languages)} language(s)"}

import json
import re
from core.models import Review, Response
from sqlalchemy.orm import Session
from datetime import datetime

LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "ar": "Arabic",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "tr": "Turkish", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"
}

async def generate_responses(review, db, llm_client, product_desc=""):
    language = LANG_NAMES.get(review.language, "English")
    prompt = (
        "Respond in JSON only with this structure, keep each response under 60 words:\n"
        + '{"professional": "...", "friendly": "...", "supportive": "..."}\n'
        + f"Reply in {language} to this review: {review.review_text[:400]}"
    )
    try:
        result = await llm_client.complete(prompt, max_tokens=800)
        clean = result.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        data = json.loads(match.group()) if match else {}
    except Exception:
        data = {}

    existing = db.query(Response).filter(Response.review_id == review.id).first()
    if existing:
        existing.response_professional = data.get("professional", "Thank you for your feedback.")
        existing.response_friendly = data.get("friendly", "Thanks so much for sharing!")
        existing.response_supportive = data.get("supportive", "We appreciate your input.")
        db.commit()
        return existing

    response = Response(
        review_id=review.id,
        user_id=review.user_id,
        response_professional=data.get("professional", "Thank you for your feedback."),
        response_friendly=data.get("friendly", "Thanks so much for sharing!"),
        response_supportive=data.get("supportive", "We appreciate your input."),
    )
    db.add(response)
    review.processed_at = datetime.utcnow()
    db.commit()
    db.refresh(response)
    return response

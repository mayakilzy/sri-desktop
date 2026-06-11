import json
import re
from sqlalchemy.orm import Session
from core.models import Review
from datetime import datetime

CLASSIFICATION_PROMPT = """Analyze this customer review and classify it.
Review: \"{review_text}\"
Respond in JSON only:
{{"review_type": "question|complaint|suggestion|praise|abuse",
  "priority_level": "low|medium|high|critical",
  "sentiment": "positive|neutral|negative|angry",
  "summary": "one sentence summary in English"}}
Rules: complaint+angry=critical, question=high, praise=low, abuse=low"""

def parse_llm_json(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"review_type": "question", "priority_level": "medium", "sentiment": "neutral", "summary": "Could not classify"}

async def classify_review(review_text, llm_client):
    prompt = CLASSIFICATION_PROMPT.format(review_text=review_text[:500])
    try:
        result = await llm_client.complete(prompt)
        return parse_llm_json(result)
    except Exception as e:
        return {"review_type": "question", "priority_level": "medium", "sentiment": "neutral", "summary": str(e)}

async def classify_batch(review_ids, db, llm_client):
    results = {"classified": 0, "failed": 0}
    for review_id in review_ids:
        review = db.query(Review).filter(Review.id == review_id).first()
        if not review:
            continue
        try:
            c = await classify_review(review.review_text, llm_client)
            review.review_type = c["review_type"]
            review.priority_level = c["priority_level"]
            review.sentiment = c["sentiment"]
            review.processed_at = datetime.utcnow()
            db.commit()
            results["classified"] += 1
        except Exception:
            results["failed"] += 1
    return results

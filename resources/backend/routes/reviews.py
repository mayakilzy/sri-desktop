from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from modules.review_importer import import_reviews
from modules.classifier import classify_batch
from modules.response_generator import generate_responses
from utils.llm_client import get_llm_client
from core.models import Review, Response
from core.schemas import ReviewOut, ResponseOut, ImportResult
from typing import List, Optional
import json

router = APIRouter(prefix="/api")

@router.post("/reviews/import")
async def import_reviews_endpoint(
    file: UploadFile = File(...),
    platform: Optional[str] = None,
    db: Session = Depends(get_db)
):
    content = await file.read()
    try:
        result = import_reviews(content, db, platform_override=platform)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reviews")
async def get_reviews(
    platform: Optional[str] = None,
    review_type: Optional[str] = None,
    priority: Optional[str] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(Review)
    if platform:   query = query.filter(Review.platform == platform)
    if review_type: query = query.filter(Review.review_type == review_type)
    if priority:   query = query.filter(Review.priority_level == priority)
    if language:   query = query.filter(Review.language == language)
    total = query.count()
    reviews = query.order_by(Review.imported_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "reviews": [
        {
            "id": r.id,
            "platform": r.platform,
            "review_text": r.review_text,
            "author_name": r.author_name,
            "rating": r.rating,
            "language": r.language,
            "review_type": r.review_type,
            "priority_level": r.priority_level,
            "sentiment": r.sentiment,
            "responded": r.responded,
            "imported_at": r.imported_at.isoformat() if r.imported_at else None,
        } for r in reviews
    ]}

@router.post("/reviews/{review_id}/generate")
async def generate_response(
    review_id: int,
    provider: Optional[str] = "gemini",
    api_key: Optional[str] = None,
    model_tier: Optional[str] = "balanced",
    db: Session = Depends(get_db)
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if not review.review_type:
        review.review_type = "general"
        review.sentiment = "neutral"
        db.commit()
    llm = get_llm_client(provider=provider, api_key=api_key, model_tier=model_tier)
    response = await generate_responses(review, db, llm)
    return {
        "review_id": review_id,
        "language": review.language,
        "professional": response.response_professional,
        "friendly": response.response_friendly,
        "supportive": response.response_supportive,
    }

@router.post("/reviews/{review_id}/respond")
async def mark_responded(
    review_id: int,
    selected_tone: str = "professional",
    db: Session = Depends(get_db)
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.responded = True
    response = db.query(Response).filter(Response.review_id == review_id).first()
    if response:
        response.selected_tone = selected_tone
    db.commit()
    return {"success": True, "review_id": review_id}

@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    total = db.query(Review).count()
    responded = db.query(Review).filter(Review.responded == True).count()
    pending = total - responded
    from sqlalchemy import func
    langs = db.query(Review.language, func.count(Review.id)).group_by(Review.language).all()
    types = db.query(Review.review_type, func.count(Review.id)).group_by(Review.review_type).all()
    return {
        "total": total,
        "responded": responded,
        "pending": pending,
        "by_language": {l: c for l, c in langs if l},
        "by_type": {t: c for t, c in types if t},
    }
import re
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from config.database import get_db
from core.models import Review
from utils.llm_client import get_llm_client
from config.settings import settings

def build_review_prompt(limit: int = 0) -> str:
    limit_instruction = f"Extract UP TO {limit} reviews only." if limit > 0 else "Extract ALL reviews you find."
    return f"""You are a review data extractor. {limit_instruction}

For each review, extract EXACTLY:
- author: reviewer username/name
- rating: number of stars (1-5), look for "X stars" or "X tacos"
- date: review date (e.g. "Jun 5, 2026")
- title: review headline/title
- body: full review text (ignore founder/team responses)

Rules:
- IGNORE cookies, navigation, ads, footer content
- IGNORE founder/team responses
- ONLY extract actual customer reviews
- If a field is missing, use null
- Return ONLY valid JSON, no markdown, no explanation

Return format:
{{"reviews": [{{"author": "username", "rating": 4, "date": "Jun 5, 2026", "title": "Review title", "body": "Review text..."}}], "total_found": 10, "product": "product name"}}

WEBPAGE CONTENT:
"""

@router.post("/reviews/scrape-url")
async def scrape_reviews_from_url(request: Request, db: Session = Depends(get_db)):
    """Scrape reviews from a URL using Scrapling + AI extraction"""
    body = await request.json()
    url          = body.get("url", "").strip()
    platform     = body.get("platform", "appsumo")
    limit        = int(body.get("limit", 0))        # 0 = all reviews
    content_size = int(body.get("content_size", 30000))  # chars to send to AI

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Auto-add /reviews/ for AppSumo product URLs
    if "appsumo.com/products/" in url:
        # Remove query params first, add /reviews/, then ignore params
        base_url = url.split("?")[0].rstrip("/")
        if not base_url.endswith("/reviews"):
            base_url = base_url + "/reviews/"
        url = base_url

    # Detect platform from URL
    if "appsumo.com" in url:
        platform = "appsumo"
    elif "gumroad.com" in url:
        platform = "gumroad"
    elif "etsy.com" in url:
        platform = "etsy"
    elif "amazon.com" in url:
        platform = "amazon"

    try:
        # Step 1: Scrape with curl_cffi via Scrapling container
        # Use __NEXT_DATA__ extraction for AppSumo (much better than markdown)
        import subprocess, json as json_mod

        if "appsumo.com" in url:
            pages_needed = max(1, (limit + 19) // 20) if limit > 0 else 5
            # Direct Python scraping - no Docker needed!
            try:
                from curl_cffi import requests as cffi_requests
                from bs4 import BeautifulSoup
                import time as time_mod

                # Step 1: Get deal_id
                r = cffi_requests.get(url, impersonate='chrome')
                soup = BeautifulSoup(r.text, 'lxml')
                script = soup.find('script', id='__NEXT_DATA__')
                if not script:
                    raise Exception("No NEXT_DATA found")
                data = json_mod.loads(script.string)
                props = data['props']['pageProps']
                deal_id = props.get('deal', {}).get('id')
                product_name = props.get('deal', {}).get('public_name', 'AppSumo Product')
                if not deal_id:
                    raise Exception("No deal_id found")

                # Step 2: Fetch from official API
                headers = {'Accept': 'application/json', 'Referer': 'https://appsumo.com/', 'X-Requested-With': 'XMLHttpRequest'}
                all_reviews = []
                total = 0
                session = cffi_requests.Session()

                for page in range(1, pages_needed + 1):
                    api_url = f'https://appsumo.com/api/v2/deals/{deal_id}/reviews/?page={page}&sort=date&order=desc&enroll=true&items_per_page=20'
                    resp = session.get(api_url, headers=headers, impersonate='chrome')
                    if resp.status_code != 200:
                        break
                    rdata = resp.json()
                    comments = rdata.get('comments', [])
                    total = rdata.get('meta', {}).get('total', 0)
                    if not comments:
                        break
                    for c in comments:
                        if c.get('comment'):
                            all_reviews.append({
                                'author': c.get('user', {}).get('username', 'Anonymous'),
                                'rating': c.get('rating', 0),
                                'date': c.get('created', '')[:10],
                                'title': c.get('title', ''),
                                'body': c.get('comment', '')
                            })
                    if limit > 0 and len(all_reviews) >= limit:
                        break
                    time_mod.sleep(1)

                if limit > 0:
                    all_reviews = all_reviews[:limit]

                next_data = {'reviews': all_reviews, 'total': total, 'product': product_name}
            except Exception as scrape_err:
                next_data = {'error': str(scrape_err)}

            if True:
                try:
                    next_data = next_data
                    if "error" not in next_data:
                        reviews_data = next_data.get("reviews", [])
                        product_name = next_data.get("product", platform)

                        saved, skipped = [], 0
                        for r in reviews_data:
                            if not r.get("body"):
                                continue
                            existing = db.query(Review).filter(
                                Review.review_text == r["body"],
                                Review.platform == platform
                            ).first()
                            if existing:
                                skipped += 1
                                continue
                            review = Review(
                                user_id="default",
                                platform=platform,
                                review_text=r.get("body", ""),
                                author_name=r.get("author", "Anonymous"),
                                rating=float(r["rating"]) if r.get("rating") else None,
                                review_url=url,
                            )
                            db.add(review)
                            saved.append(review)
                        db.commit()
                        for r in saved:
                            db.refresh(r)

                        return {
                            "success": True,
                            "url": url,
                            "platform": platform,
                            "product": product_name,
                            "llm_provider": "direct",
                            "llm_model": "AppSumo API v2",
                            "total_found": len(reviews_data),
                            "saved": len(saved),
                            "skipped_duplicates": skipped,
                            "preview": [
                                {"id": r.id, "author": r.author_name, "rating": r.rating, "text": r.review_text[:80] + "..."}
                                for r in saved[:5]
                            ]
                        }
                except Exception:
                    pass  # Fall through to AI extraction


        # Fallback: Scrape with Scrapling markdown + AI
        async with httpx.AsyncClient(timeout=90.0) as client:
            scrape_resp = await client.post("http://localhost:8920/scrape", json={
                "url": url,
                "render": True,
                "wait_for": 10000,
                "output_format": "markdown"
            })

        if scrape_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Scraping service unavailable")

        content = scrape_resp.json().get("content", "")

        if not content or len(content) < 200:
            raise HTTPException(status_code=422, detail="Could not extract content from URL")

        # Step 2: AI extraction using user's configured provider
        # Read settings from DB (saved via /settings/llm)
        db_settings = {r.key: r.value for r in db.query(AppSetting).all()}
        provider   = db_settings.get("llm_provider", "gemini")
        api_key    = db_settings.get(f"{provider}_api_key", getattr(settings, f"{provider}_api_key", ""))
        model_tier = db_settings.get("llm_model_tier", "balanced")

        llm = get_llm_client(provider=provider, api_key=api_key, model_tier=model_tier)

        ai_response = await llm.complete(
            prompt=build_review_prompt(limit) + content[:content_size],
            max_tokens=4000
        )

        # Parse AI response
        try:
            clean = ai_response.strip().replace("```json", "").replace("```", "").strip()
            extracted = json.loads(clean)
        except Exception:
            match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if match:
                extracted = json.loads(match.group())
            else:
                raise HTTPException(status_code=422, detail="AI could not parse reviews from page")

        reviews_data = extracted.get("reviews", [])
        product_name = extracted.get("product", platform)

        # Step 3: Save to DB
        saved, skipped = [], 0

        for r in reviews_data:
            if not r.get("body"):
                continue

            existing = db.query(Review).filter(
                Review.review_text == r["body"],
                Review.platform == platform
            ).first()

            if existing:
                skipped += 1
                continue

            review = Review(
                user_id="default",
                platform=platform,
                review_text=r.get("body", ""),
                author_name=r.get("author", "Anonymous"),
                rating=float(r["rating"]) if r.get("rating") else None,
                review_url=url,
            )
            db.add(review)
            saved.append(review)

        db.commit()
        for r in saved:
            db.refresh(r)

        return {
            "success": True,
            "url": url,
            "platform": platform,
            "product": product_name,
            "llm_provider": provider,
            "llm_model": llm.get_model(),
            "total_found": len(reviews_data),
            "saved": len(saved),
            "skipped_duplicates": skipped,
            "preview": [
                {"id": r.id, "author": r.author_name, "rating": r.rating, "text": r.review_text[:80] + "..."}
                for r in saved[:5]
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
# ─── App Settings (key-value store in DB) ──────────────────────
from sqlalchemy import Column, String, Text
from config.database import Base, engine

class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"extend_existing": True}
    key   = Column(String, primary_key=True)
    value = Column(Text, default="")

Base.metadata.create_all(bind=engine)

@router.post("/settings/llm")
async def save_llm_settings(request: Request, db: Session = Depends(get_db)):
    body       = await request.json()
    provider   = body.get("provider", "gemini")
    api_key    = body.get("apiKey", "")
    model_tier = body.get("modelTier", "balanced")
    for k, v in [("llm_provider", provider), (f"{provider}_api_key", api_key), ("llm_model_tier", model_tier)]:
        row = db.query(AppSetting).filter(AppSetting.key == k).first()
        if row:
            row.value = v
        else:
            db.add(AppSetting(key=k, value=v))
    db.commit()
    return {"success": True, "provider": provider, "model_tier": model_tier}

@router.get("/settings/llm")
async def get_llm_settings(db: Session = Depends(get_db)):
    rows     = {r.key: r.value for r in db.query(AppSetting).all()}
    provider = rows.get("llm_provider", "gemini")
    return {
        "provider":   provider,
        "model_tier": rows.get("llm_model_tier", "balanced"),
        "has_key":    bool(rows.get(f"{provider}_api_key", "")),
    }

@router.post("/settings/llm/test")
async def test_llm_connection(request: Request):
    body       = await request.json()
    provider   = body.get("provider", "gemini")
    api_key    = body.get("apiKey", "")
    model_tier = body.get("modelTier", "balanced")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key required")
    try:
        from utils.llm_client import get_llm_client
        llm    = get_llm_client(provider=provider, api_key=api_key, model_tier=model_tier)
        result = await llm.complete("Say OK only.", max_tokens=10)
        return {"success": True, "provider": provider, "model": llm.get_model()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/insights")
async def get_insights(db: Session = Depends(get_db)):
    """Product insights with AI recommendations"""
    from sqlalchemy import func
    reviews = db.query(Review).all()
    if not reviews:
        raise HTTPException(status_code=404, detail="No reviews found")

    # Basic stats
    total = len(reviews)
    ratings = [r.rating for r in reviews if r.rating]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0

    # Rating distribution
    rating_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings:
        key = round(r)
        if key in rating_dist:
            rating_dist[key] += 1

    # Language distribution
    lang_dist = {}
    for r in reviews:
        lang = r.language or "unknown"
        lang_dist[lang] = lang_dist.get(lang, 0) + 1

    # Sentiment distribution
    sentiment_dist = {}
    for r in reviews:
        s = r.sentiment or "unknown"
        sentiment_dist[s] = sentiment_dist.get(s, 0) + 1

    # Review types
    type_dist = {}
    for r in reviews:
        t = r.review_type or "general"
        type_dist[t] = type_dist.get(t, 0) + 1

    # Get sample reviews for AI analysis
    sample_texts = [r.review_text[:200] for r in reviews[:20]]

    return {
        "total_reviews": total,
        "avg_rating": round(avg_rating, 2),
        "rating_distribution": rating_dist,
        "language_distribution": lang_dist,
        "sentiment_distribution": sentiment_dist,
        "type_distribution": type_dist,
        "sample_count": len(sample_texts),
        "needs_ai_analysis": True,
    }

@router.post("/insights/analyze")
async def analyze_insights(db: Session = Depends(get_db)):
    """AI-powered analysis of reviews"""
    from utils.llm_client import get_llm_client
    from config.database import SessionLocal

    reviews = db.query(Review).all()
    if not reviews:
        raise HTTPException(status_code=404, detail="No reviews found")

    # Get settings from DB
    db_settings = {r.key: r.value for r in db.query(AppSetting).all()}
    provider   = db_settings.get("llm_provider", "gemini")
    api_key    = db_settings.get(f"{provider}_api_key", "")
    model_tier = db_settings.get("llm_model_tier", "fast")

    if not api_key:
        raise HTTPException(status_code=400, detail="No API key configured")

    # Prepare reviews for analysis
    sample = reviews[:30]
    reviews_text = "\n".join([
        f"- [{r.rating}★] {r.review_text[:150]}"
        for r in sample if r.review_text
    ])

    prompt = f"""Analyze these {len(sample)} product reviews and provide structured insights.

REVIEWS:
{reviews_text}

Provide a JSON response with exactly this structure:
{{
  "top_complaints": ["complaint 1", "complaint 2", "complaint 3"],
  "top_praises": ["praise 1", "praise 2", "praise 3"],
  "key_insights": ["insight 1", "insight 2", "insight 3"],
  "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"],
  "overall_sentiment": "positive|neutral|negative",
  "summary": "2-3 sentence summary of overall customer sentiment"
}}

Return ONLY valid JSON, no markdown."""

    try:
        llm = get_llm_client(provider=provider, api_key=api_key, model_tier=model_tier)
        result = await llm.complete(prompt, max_tokens=1000)
        clean = result.strip().replace("```json", "").replace("```", "").strip()
        analysis = json.loads(clean)
        return {"success": True, "analysis": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Knowledge Base ─────────────────────────────────────────────
from core.models import KnowledgeBase

@router.get("/knowledge-base")
async def get_knowledge_base(db: Session = Depends(get_db)):
    items = db.query(KnowledgeBase).filter(KnowledgeBase.user_id == "default").all()
    return {"items": [{"id": i.id, "category": i.category, "title": i.title, "content": i.content, "created_at": str(i.created_at)} for i in items]}

@router.post("/knowledge-base")
async def add_knowledge_base(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    item = KnowledgeBase(
        user_id="default",
        category=body.get("category", "faq"),
        title=body.get("title", ""),
        content=body.get("content", ""),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"success": True, "id": item.id}

@router.delete("/knowledge-base/{item_id}")
async def delete_knowledge_base(item_id: int, db: Session = Depends(get_db)):
    item = db.query(KnowledgeBase).filter(KnowledgeBase.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(item)
    db.commit()
    return {"success": True}

@router.post("/competitor/analyze")
async def analyze_competitor(request: Request, db: Session = Depends(get_db)):
    body       = await request.json()
    url        = body.get("url", "")
    product    = body.get("product", "competitor")
    provider   = body.get("provider", "gemini")
    api_key    = body.get("apiKey", "")
    model_tier = body.get("modelTier", "fast")

    # Get recent competitor reviews from DB
    comp_reviews = db.query(Review).filter(
        Review.review_url == url.rstrip("/") + "/reviews/"
    ).limit(30).all()

    if not comp_reviews:
        comp_reviews = db.query(Review).order_by(Review.id.desc()).limit(20).all()

    reviews_text = "\n".join([
        f"- [{r.rating}★] {r.review_text[:150]}"
        for r in comp_reviews if r.review_text
    ])

    prompt = f"""Analyze these competitor product reviews for "{product}" and provide strategic insights.

COMPETITOR REVIEWS:
{reviews_text}

Return ONLY valid JSON:
{{
  "summary": "2-3 sentence overview of competitor strengths/weaknesses",
  "weaknesses": ["weakness 1", "weakness 2", "weakness 3"],
  "opportunities": ["opportunity 1", "opportunity 2", "opportunity 3"],
  "positioning": ["positioning tip 1", "positioning tip 2", "positioning tip 3"]
}}"""

    try:
        from utils.llm_client import get_llm_client
        llm    = get_llm_client(provider=provider, api_key=api_key, model_tier=model_tier)
        result = await llm.complete(prompt, max_tokens=800)
        clean  = result.strip().replace("```json","").replace("```","").strip()
        return {"success": True, "analysis": json.loads(clean)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import StreamingResponse
import io, csv

@router.get("/export/csv")
async def export_csv(db: Session = Depends(get_db)):
    reviews = db.query(Review).all()
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(["id","platform","author","rating","language","review_type","review_text","responded","date"])
    for r in reviews:
        writer.writerow([r.id, r.platform, r.author_name, r.rating, r.language, r.review_type, r.review_text, r.responded, r.imported_at])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reviews_export.csv"})

@router.get("/export/json")
async def export_json(db: Session = Depends(get_db)):
    reviews = db.query(Review).all()
    data    = [{"id": r.id, "platform": r.platform, "author": r.author_name, "rating": r.rating,
                "language": r.language, "type": r.review_type, "text": r.review_text,
                "responded": r.responded, "date": str(r.imported_at)} for r in reviews]
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return StreamingResponse(io.BytesIO(content.encode()), media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=reviews_export.json"})

@router.delete("/reviews/clear-all")
async def clear_all_data(db: Session = Depends(get_db)):
    db.query(Review).delete()
    db.query(AppSetting).delete()
    db.commit()
    return {"success": True, "message": "All data cleared"}

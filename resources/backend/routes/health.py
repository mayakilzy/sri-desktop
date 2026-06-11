from fastapi import APIRouter
from datetime import datetime

router = APIRouter(prefix="/api")

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Smart Review Intelligence API",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

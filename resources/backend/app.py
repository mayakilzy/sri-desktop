from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.database import engine, Base
from core import models
from routes.health import router as health_router
import os, logging

Base.metadata.create_all(bind=engine)

os.makedirs("/root/data/sri/logs", exist_ok=True)
logging.basicConfig(
    filename="/root/data/sri/logs/app.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

app = FastAPI(
    title="Smart Review Intelligence API",
    description="AI-powered review response generator",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sri.agentcraft.info", "http://localhost:3010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["Health"])

from routes.reviews import router as reviews_router
app.include_router(reviews_router, tags=["Reviews"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3011)

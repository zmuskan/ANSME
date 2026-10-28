import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.analyze import router as analyze_router
from app.db.database import Base, engine
from app.models.analysis import Analysis
from app.models.evidence import Evidence
from app.models.price_history import PriceHistory
from app.models.user_preference import UserPreference
from app.api.history import router as history_router
from app.api.analytics import router as analytics_router
from app.api.leaderboard import router as leaderboard_router

fastapi_app = FastAPI(
    title="ANSME Decision Engine",
    version="1.0.0"
)

fastapi_app.include_router(health_router)
fastapi_app.include_router(analyze_router)
fastapi_app.include_router(history_router)
fastapi_app.include_router(analytics_router)
fastapi_app.include_router(leaderboard_router)


@fastapi_app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)


@fastapi_app.get("/")
def root():
    return {
        "message": "ANSME Backend Running"
    }


allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_URLS",
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]

app = CORSMiddleware(
    app=fastapi_app,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from src.config.settings import get_settings
from src.db.connection import init_db
from src.middlewares.logger import setup_logger
from src.middlewares.error_handler import (
    AppException,
    app_exception_handler,
    unhandled_exception_handler,
)
from src.routes import message as message_route
from src.routes import memory as memory_route
from src.routes import profile as profile_route
from src.routes import user as user_route
from src.routes import chat as chat_route        # NEW
from src.routes import admin as admin_route      # NEW
from src.jobs.decay_job import run_decay_job
from src.jobs.summarization_job import run_summarization_job
from src.jobs.cleanup_job import run_cleanup_job

settings = get_settings()
setup_logger()

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Axiom Remember API...")
    await init_db()

    scheduler.add_job(run_decay_job,         "interval", seconds=settings.decay_job_interval,    id="decay_job")
    scheduler.add_job(run_summarization_job, "interval", seconds=settings.summarize_job_interval, id="summarization_job")
    scheduler.add_job(run_cleanup_job,       "interval", seconds=settings.cleanup_job_interval,   id="cleanup_job")
    scheduler.start()
    logger.info("Background jobs started: decay / summarization / cleanup")

    yield

    scheduler.shutdown()
    logger.info("Axiom Remember API shut down")


app = FastAPI(
    title="Axiom Remember API",
    description="Production-grade AI memory engine with selective retention, decay, evolution, and semantic retrieval.",
    version=settings.app_version,
    lifespan=lifespan,
)

# ── Rate limiting (optional — enabled when slowapi is installed) ───────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Wire the limiter into the chat route module so it can use @limiter.limit
    chat_route.set_limiter(limiter)
    logger.info("Rate limiting enabled via slowapi")
except ImportError:
    logger.warning("slowapi not installed — rate limiting disabled. Run: pip install slowapi")

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(user_route.router)
app.include_router(message_route.router)
app.include_router(memory_route.router)
app.include_router(profile_route.router)
app.include_router(chat_route.router)            # NEW — prefix="/chat"
app.include_router(admin_route.router)           # NEW — prefix="/admin"


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": settings.app_version}

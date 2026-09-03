from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging, get_logger
from app.phone_relay.ws_endpoint import router as phone_relay_router
from app.routes.lowes import router as lowes_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Lowe's PDP scraper API")
    yield
    logger.info("Shutting down")


app = FastAPI(title="Lowe's PDP Scraper API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.CORS_ORIGIN == "*" else [settings.CORS_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lowes_router)
app.include_router(phone_relay_router)

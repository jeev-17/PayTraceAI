
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401 - register model metadata before table creation
from app.config import settings
from app.database import Base, engine
from app.routers import incidents, orders, simulations, webhooks
from app.schemas import HealthResponse

logger = logging.getLogger(__name__)


def normalize_origin(origin: str) -> str:
    origin = origin.rstrip("/")
    if origin.startswith(("http://", "https://")):
        return origin
    return f"https://{origin}"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="PayTrace AI",
    version="0.1.0",
    lifespan=lifespan,
)

# Register API routers
app.include_router(orders.router)
app.include_router(webhooks.router)
app.include_router(incidents.router)
app.include_router(simulations.router)

# Configure frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[normalize_origin(settings.frontend_origin)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    _: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
            }
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request did not match the required schema.",
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unhandled application error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected application error occurred.",
            }
        },
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        config_present=settings.config_presence(),
    )

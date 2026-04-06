from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.deps import firebase_claims
from app.config import settings
from app.database import close_db, connect_db, get_database
from app.firebase_service import init_firebase_admin
from app.routers import advisors, students, auth, bookings, upload, payments
from app.s3_service import s3_configured
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    try:
        init_firebase_admin()
    except Exception as e:
        print(f"CRITICAL: Firebase Admin initialization failed: {e!s}")
    start_scheduler()
    yield
    stop_scheduler()
    await close_db()


app = FastAPI(title="CollegeConnect API", lifespan=lifespan)

# CORS configuration: handle "allow_credentials" correctly with wildcard origin
origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]

# If origins is just ["*"], we must set allow_credentials=False for FastAPI.
# If we need credentials (cookies/auth), we should list specific domains.
allow_credentials = True
if "*" in origins:
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(students.router, prefix="/api")
app.include_router(advisors.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(bookings.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(payments.router, prefix="/api")


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta/s3")
async def meta_s3(claims: dict = Depends(firebase_claims)) -> dict[str, str | bool]:
    """Check S3 config status. Restricted to authenticated users."""
    return {
        "configured": s3_configured(),
        "bucket": settings.s3_bucket if s3_configured() else "",
        "region": settings.aws_region if s3_configured() else "",
        "prefix": (settings.s3_college_ids_prefix or "college-ids").strip().strip("/"),
    }


@app.get("/api/meta/db-stats")
async def db_stats(claims: dict = Depends(firebase_claims)) -> dict[str, str | int]:
    """Database stats and collection names. Restricted to authenticated users."""
    db = get_database()
    return {
        "database_name": settings.database_name,
        "students_count": await db.students.estimated_document_count(),
        "advisors_count": await db.advisors.estimated_document_count(),
    }


@app.api_route("/", methods=["GET", "HEAD"])
async def root() -> dict[str, str]:
    return {
        "message": "CollegeConnect API",
        "collections": "MongoDB: students, advisors",
    }

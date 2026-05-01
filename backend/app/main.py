from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api.routes_auth import router as auth_router
from app.api.routes_documents import router as documents_router
from app.api.routes_review import router as review_router
from app.api.routes_submissions import router as submissions_router
from app.api.routes_ui import router as ui_router
from app.config import get_settings
from app.core.security import hash_password
from app.db.database import AsyncSessionLocal, init_db
from app.db.models import User, UserRole


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        n = await session.scalar(select(func.count()).select_from(User))
        if n == 0:
            session.add(
                User(
                    email="reviewer@poc.local",
                    hashed_password=hash_password("Reviewer123!"),
                    role=UserRole.reviewer,
                )
            )
            await session.commit()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)

static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth_router, prefix="/api")
app.include_router(submissions_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(ui_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

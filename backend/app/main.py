"""FastAPI 入口"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, files, pages, search, misc


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表
    Base.metadata.create_all(bind=engine)
    logging.basicConfig(level=logging.INFO)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(pages.router)
app.include_router(search.router)
app.include_router(misc.router)


@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.app_name}

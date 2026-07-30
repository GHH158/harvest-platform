from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator

from .config import ROOT_DIR, get_settings
from .db import apply_schema, make_engine
from .repository import Repository


class MaterialCreate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    text: str | None = Field(default=None, max_length=100_000)
    url: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def has_exactly_one_source(self) -> MaterialCreate:
        if bool(self.text and self.text.strip()) == bool(self.url and self.url.strip()):
            raise ValueError("请粘贴文本或输入一个链接，二选一。")
        return self


def title_for_text(value: str) -> str:
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "未命名材料")
    return f"{first_line[:36]}{'…' if len(first_line) > 36 else ''}"


def title_for_url(value: str) -> str:
    return urlparse(value).netloc or "网页材料"


def serialise_material(material: dict) -> dict:
    settings = get_settings()
    audio_key = material.pop("audio_oss_key", None)
    material["audio_url"] = (
        f"{settings.oss_public_base_url.rstrip('/')}/{audio_key}"
        if audio_key and settings.oss_public_base_url
        else None
    )
    return material


@asynccontextmanager
async def lifespan(_: FastAPI):
    apply_schema(make_engine())
    yield


app = FastAPI(title="Harvest", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "backend" / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT_DIR / "backend" / "app" / "templates")


def repository() -> Repository:
    return Repository(make_engine())


def create_material(payload: MaterialCreate) -> tuple[int, int]:
    repo = repository()
    if payload.text and payload.text.strip():
        source_text = payload.text.strip()
        return repo.create_material_with_job(
            title=(payload.title or "").strip() or title_for_text(source_text),
            source_type="paste",
            source_ref=None,
            job_kind="tts",
            payload={"text": source_text},
        )
    assert payload.url
    source_url = payload.url.strip()
    return repo.create_material_with_job(
        title=(payload.title or "").strip() or title_for_url(source_url),
        source_type="url",
        source_ref=source_url,
        job_kind="fetch",
        payload={"url": source_url},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/materials", status_code=status.HTTP_202_ACCEPTED)
def post_material(payload: MaterialCreate) -> dict[str, int | str]:
    material_id, job_id = create_material(payload)
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.get("/materials")
def get_materials() -> list[dict]:
    return [serialise_material(item) for item in repository().list_materials()]


@app.get("/materials/{material_id}")
def get_material(material_id: int) -> dict:
    material = repository().get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    material["segments"] = repository().get_segments(material_id)
    return serialise_material(material)


@app.get("/materials/{material_id}/segments")
@app.get("/segments")
def get_segments(material_id: int) -> list[dict]:
    material = repository().get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    return repository().get_segments(material_id)


@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    job = repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job


@app.get("/ingest-web", response_class=HTMLResponse)
def ingest_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "ingest.html", {"error": error})


@app.post("/ingest-web", response_class=HTMLResponse)
def ingest_form(
    request: Request,
    title: Annotated[str | None, Form()] = None,
    source_text: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
):
    try:
        material_id, _ = create_material(
            MaterialCreate(title=title, text=source_text, url=source_url)
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request, "ingest.html", {"error": str(error)}, status_code=422
        )
    return RedirectResponse(
        url=f"/ingest-web?created={material_id}", status_code=status.HTTP_303_SEE_OTHER
    )

from fastapi import APIRouter, UploadFile, File, Form, Request, BackgroundTasks, HTTPException
from pydantic import BaseModel
from uuid import UUID
import tempfile, os

from services.search.searcher import search_citations
from services.ingestion.ingestor import ingest_paper
from api.session import create_session
from shared.database import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter()


# ─────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────

class SearchRequest(BaseModel):
    text: str
    top_k: int = 10


@router.post("/search")
async def search(req: SearchRequest, request: Request):
    """
    Main endpoint. Student sends text, gets back ranked citations.
    """
    if len(req.text.strip()) < 20:
        raise HTTPException(400, "Text too short — send at least a paragraph.")

    session_id = await create_session(request)
    result = await search_citations(req.text, session_id=session_id, top_k=req.top_k)

    # Log submission
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO submissions (session_id, input_type, input_length)
                VALUES (:sid, 'text', :len)
            """),
            {"sid": session_id, "len": len(req.text)}
        )
        await db.commit()

    return result


@router.post("/search/click")
async def track_click(chunk_id: str, submission_id: str):
    """Called when student clicks a citation result."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                UPDATE suggestion_results SET was_clicked = true
                WHERE chunk_id = :cid AND submission_id = :sid
            """),
            {"cid": chunk_id, "sid": submission_id}
        )
        await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────
# INGESTION
# ─────────────────────────────────────────

@router.post("/papers")
async def upload_paper(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    authors: str = Form(""),         # comma-separated
    year: int = Form(None),
    doi: str = Form(None),
    language: str = Form("en"),
    field_slug: str = Form(None),
    file: UploadFile = File(...),
):
    """
    Upload a PDF paper. Ingestion (chunking + embedding) runs in background.
    Returns paper_id immediately so the frontend can show progress.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    # Resolve field_id
    field_id = None
    if field_slug:
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                text("SELECT id FROM fields WHERE slug = :slug"), {"slug": field_slug}
            )
            row = res.fetchone()
            if row:
                field_id = str(row[0])

    # Create paper record
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("""
                INSERT INTO papers (title, authors, year, doi, language, field_id)
                VALUES (:title, :authors, :year, :doi, :language, :field_id)
                RETURNING id
            """),
            {
                "title": title,
                "authors": [a.strip() for a in authors.split(",") if a.strip()],
                "year": year,
                "doi": doi or None,
                "language": language,
                "field_id": field_id,
            }
        )
        paper_id = res.fetchone()[0]
        await db.commit()

    # Save PDF to temp file and kick off background ingestion
    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(content)
    tmp.close()

    background_tasks.add_task(_run_ingestion, paper_id, tmp.name)

    return {"paper_id": str(paper_id), "status": "ingesting"}


async def _run_ingestion(paper_id, pdf_path: str):
    try:
        count = await ingest_paper(paper_id, pdf_path)
        print(f"[ingestion] paper={paper_id} chunks={count}")
    finally:
        os.unlink(pdf_path)


# ─────────────────────────────────────────
# FEEDBACK
# ─────────────────────────────────────────

class FeedbackRequest(BaseModel):
    submission_id: str
    rating: int
    comment: str = ""


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    if not (1 <= req.rating <= 5):
        raise HTTPException(400, "Rating must be 1–5.")

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO feedback (submission_id, rating, comment)
                VALUES (:sid, :rating, :comment)
            """),
            {"sid": req.submission_id, "rating": req.rating, "comment": req.comment}
        )
        await db.commit()

    return {"ok": True}

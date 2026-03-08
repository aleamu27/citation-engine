import fitz  # PyMuPDF
import hashlib
from uuid import UUID
from langchain_text_splitters import RecursiveCharacterTextSplitter
from services.embedding.embedder import embed_passages
from shared.config import get_settings
from shared.database import AsyncSessionLocal
from sqlalchemy import text

settings = get_settings()

splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def extract_text_from_pdf(path: str) -> list[dict]:
    """Returns list of {page_number, text} dicts."""
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc):
        pages.append({"page_number": i + 1, "text": page.get_text()})
    doc.close()
    return pages


def chunk_pages(pages: list[dict]) -> list[dict]:
    """Split pages into chunks, preserving page_number."""
    chunks = []
    for page in pages:
        splits = splitter.split_text(page["text"])
        for split in splits:
            if len(split.strip()) > 50:  # skip tiny fragments
                chunks.append({
                    "text": split.strip(),
                    "page_number": page["page_number"],
                })
    return chunks


async def ingest_paper(
    paper_id: UUID,
    pdf_path: str,
) -> int:
    """
    Full ingestion pipeline:
    1. Extract text from PDF
    2. Split into chunks
    3. Embed chunks
    4. Insert into DB

    Returns number of chunks created.
    """
    pages = extract_text_from_pdf(pdf_path)
    chunks = chunk_pages(pages)

    if not chunks:
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = embed_passages(texts)

    async with AsyncSessionLocal() as session:
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            await session.execute(
                text("""
                    INSERT INTO chunks (paper_id, chunk_index, text, embedding, page_number)
                    VALUES (:paper_id, :chunk_index, :text, :embedding, :page_number)
                    ON CONFLICT (paper_id, chunk_index) DO UPDATE
                    SET text = EXCLUDED.text, embedding = EXCLUDED.embedding
                """),
                {
                    "paper_id": str(paper_id),
                    "chunk_index": i,
                    "text": chunk["text"],
                    "embedding": str(embedding),  # pgvector accepts '[1,2,3,...]'
                    "page_number": chunk["page_number"],
                }
            )
        await session.commit()

    return len(chunks)

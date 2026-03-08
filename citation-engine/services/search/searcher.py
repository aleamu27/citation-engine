import hashlib
import json
import time
from uuid import UUID
from sqlalchemy import text
from shared.database import AsyncSessionLocal
from shared.config import get_settings
from services.embedding.embedder import embed_query

settings = get_settings()


async def detect_field(input_text: str) -> str | None:
    """
    Simple keyword-based field detection.
    Replace with a small zero-shot classifier (e.g. facebook/bart-large-mnli)
    when you want better accuracy.
    """
    FIELD_KEYWORDS = {
        "biology": ["cell", "gene", "protein", "organism", "evolution", "DNA", "RNA", "celle", "gen"],
        "chemistry": ["molecule", "reaction", "compound", "element", "acid", "base", "molekyl"],
        "computer-science": ["algorithm", "neural", "machine learning", "software", "database", "algoritme"],
        "economics": ["market", "GDP", "inflation", "supply", "demand", "økonomi", "marked"],
        "history": ["war", "century", "empire", "revolution", "krig", "århundre"],
        "law": ["statute", "court", "legal", "rights", "lov", "rett", "paragraf"],
        "mathematics": ["theorem", "proof", "equation", "function", "integral", "teorem", "ligning"],
        "medicine": ["patient", "disease", "treatment", "diagnosis", "clinical", "pasient", "sykdom"],
        "physics": ["force", "energy", "quantum", "particle", "wave", "kraft", "energi"],
        "psychology": ["behavior", "cognition", "therapy", "mental", "adferd", "terapi"],
        "sociology": ["society", "culture", "inequality", "social", "samfunn", "kultur"],
    }

    lowered = input_text.lower()
    scores = {}
    for slug, keywords in FIELD_KEYWORDS.items():
        scores[slug] = sum(1 for kw in keywords if kw.lower() in lowered)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


async def search_citations(
    input_text: str,
    session_id: UUID | None = None,
    top_k: int | None = None,
) -> dict:
    """
    Full search pipeline:
    1. Check cache
    2. Embed query
    3. Detect field
    4. Vector search filtered by field
    5. Cache result
    6. Return citations with paper metadata
    """
    k = top_k or settings.top_k
    input_hash = hashlib.sha256(input_text.encode()).hexdigest()
    start = time.monotonic()

    async with AsyncSessionLocal() as db:
        # 1. Cache check
        cached = await db.execute(
            text("SELECT chunk_ids, scores FROM citation_cache WHERE input_hash = :h AND expires_at > now()"),
            {"h": input_hash}
        )
        row = cached.fetchone()
        if row:
            chunk_ids, scores = row
            results = await _fetch_chunks_by_ids(db, chunk_ids, scores)
            return {"results": results, "cached": True, "field": None}

        # 2. Embed
        vector = embed_query(input_text)

        # 3. Field detection
        field_slug = await detect_field(input_text)
        field_id = None
        if field_slug:
            res = await db.execute(
                text("SELECT id FROM fields WHERE slug = :slug"), {"slug": field_slug}
            )
            field_row = res.fetchone()
            if field_row:
                field_id = field_row[0]

        # 4. Vector search
        # Filter by field when detected — halves search space, improves precision
        if field_id:
            query = text("""
                SELECT c.id, c.text, c.page_number, c.paper_id,
                       1 - (c.embedding <=> :vec::vector) AS score
                FROM chunks c
                JOIN papers p ON p.id = c.paper_id
                WHERE p.field_id = :field_id
                ORDER BY c.embedding <=> :vec::vector
                LIMIT :k
            """)
            params = {"vec": str(vector), "field_id": str(field_id), "k": k}
        else:
            query = text("""
                SELECT c.id, c.text, c.page_number, c.paper_id,
                       1 - (c.embedding <=> :vec::vector) AS score
                FROM chunks c
                ORDER BY c.embedding <=> :vec::vector
                LIMIT :k
            """)
            params = {"vec": str(vector), "k": k}

        res = await db.execute(query, params)
        rows = res.fetchall()

        if not rows:
            return {"results": [], "cached": False, "field": field_slug}

        chunk_ids = [str(r[0]) for r in rows]
        scores = [float(r[4]) for r in rows]

        # Enrich with paper metadata
        results = []
        for i, row in enumerate(rows):
            paper = await db.execute(
                text("SELECT title, authors, year, doi FROM papers WHERE id = :id"),
                {"id": str(row[3])}
            )
            paper_row = paper.fetchone()
            results.append({
                "rank": i + 1,
                "chunk_id": str(row[0]),
                "text": row[1],
                "page_number": row[2],
                "score": round(float(row[4]), 4),
                "paper": {
                    "title": paper_row[0] if paper_row else None,
                    "authors": paper_row[1] if paper_row else [],
                    "year": paper_row[2] if paper_row else None,
                    "doi": paper_row[3] if paper_row else None,
                }
            })

        # 5. Cache result
        await db.execute(
            text("""
                INSERT INTO citation_cache (input_hash, field_id, chunk_ids, scores)
                VALUES (:h, :f, :c, :s)
                ON CONFLICT (input_hash) DO NOTHING
            """),
            {
                "h": input_hash,
                "f": str(field_id) if field_id else None,
                "c": chunk_ids,
                "s": scores,
            }
        )

        # 6. Log search
        latency_ms = int((time.monotonic() - start) * 1000)
        await db.execute(
            text("""
                INSERT INTO search_logs (session_id, input_length, detected_field_id, result_count, latency_ms)
                VALUES (:sid, :len, :fid, :rc, :lat)
            """),
            {
                "sid": str(session_id) if session_id else None,
                "len": len(input_text),
                "fid": str(field_id) if field_id else None,
                "rc": len(results),
                "lat": latency_ms,
            }
        )
        await db.commit()

    return {"results": results, "cached": False, "field": field_slug}


async def _fetch_chunks_by_ids(db, chunk_ids: list, scores: list) -> list:
    results = []
    for i, (chunk_id, score) in enumerate(zip(chunk_ids, scores)):
        res = await db.execute(
            text("""
                SELECT c.text, c.page_number, p.title, p.authors, p.year, p.doi
                FROM chunks c JOIN papers p ON p.id = c.paper_id
                WHERE c.id = :id
            """),
            {"id": chunk_id}
        )
        row = res.fetchone()
        if row:
            results.append({
                "rank": i + 1,
                "chunk_id": chunk_id,
                "text": row[0],
                "page_number": row[1],
                "score": round(score, 4),
                "paper": {"title": row[2], "authors": row[3], "year": row[4], "doi": row[5]}
            })
    return results

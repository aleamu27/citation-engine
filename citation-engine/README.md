# Citation Engine

Semantic citation search — students send text, get back ranked academic citations.

## Stack
- **FastAPI** — API
- **PostgreSQL + pgvector** — metadata + vector search (HNSW)
- **multilingual-e5-large** — embeddings (Norwegian + English)
- **Supabase** — hosted Postgres + file storage
- **Redis** — task queue (for future async ingestion scaling)

## Local setup

```bash
# 1. Copy env
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, DATABASE_URL, SECRET_KEY

# 2. Download GeoIP database (free, requires MaxMind account)
# https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
# Place GeoLite2-City.mmdb in project root

# 3. Start with Docker
docker compose up

# OR run locally
pip install -r requirements.txt
uvicorn main:app --reload
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/search` | Search citations for a text input |
| POST | `/api/v1/search/click` | Track which citation was clicked |
| POST | `/api/v1/papers` | Upload a PDF paper (admin) |
| POST | `/api/v1/feedback` | Submit rating + comment |
| GET  | `/health` | Health check |

### Search example
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"text": "Photosynthesis converts light energy into chemical energy stored in glucose.", "top_k": 5}'
```

### Upload paper example
```bash
curl -X POST http://localhost:8000/api/v1/papers \
  -F "title=Molecular Biology of the Cell" \
  -F "authors=Alberts, Johnson" \
  -F "year=2022" \
  -F "language=en" \
  -F "field_slug=biology" \
  -F "file=@paper.pdf"
```

## Architecture

```
Client (Next.js)
    ↓
API Gateway (FastAPI)
    ├── Session logging (IP hash + geo)
    ├── Search Service
    │     ├── Embed query (e5-large)
    │     ├── Detect field (keyword classifier)
    │     └── pgvector cosine search (filtered by field)
    └── Ingestion Service
          ├── PDF → chunks (300-500 tokens)
          ├── Embed passages (e5-large)
          └── Insert into pgvector DB
```

## Scaling path

Today (< 100k chunks): pgvector in Supabase is fine.

When you hit millions of chunks:
1. Move vector storage to **Pinecone** or **Weaviate**
2. Keep Postgres for metadata/relations
3. Move ingestion to **Celery workers** (Redis queue already wired in)

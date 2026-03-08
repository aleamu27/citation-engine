from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from shared.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Citation Engine",
    description="Semantic citation search for academic papers",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}

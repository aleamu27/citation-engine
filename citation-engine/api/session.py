import hashlib
import geoip2.database
from fastapi import Request
from shared.config import get_settings
from shared.database import AsyncSessionLocal
from sqlalchemy import text

settings = get_settings()


def hash_ip(ip: str) -> str:
    """One-way hash — can detect abuse, can't recover IP."""
    return hashlib.sha256(ip.encode()).hexdigest()


def get_geo(ip: str) -> dict:
    try:
        with geoip2.database.Reader(settings.geoip_db_path) as reader:
            response = reader.city(ip)
            return {
                "country_code": response.country.iso_code,
                "city": response.city.name,
            }
    except Exception:
        return {"country_code": None, "city": None}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


async def create_session(request: Request, user_id: str | None = None) -> str:
    ip = get_client_ip(request)
    ip_hash = hash_ip(ip)
    geo = get_geo(ip)
    user_agent = request.headers.get("User-Agent", "")

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("""
                INSERT INTO sessions (user_id, ip_hash, user_agent, country_code, city)
                VALUES (:uid, :ip_hash, :ua, :cc, :city)
                RETURNING id
            """),
            {
                "uid": user_id,
                "ip_hash": ip_hash,
                "ua": user_agent[:512],
                "cc": geo["country_code"],
                "city": geo["city"],
            }
        )
        session_id = res.fetchone()[0]
        await db.commit()

    return str(session_id)

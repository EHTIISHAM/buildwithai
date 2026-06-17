"""
BuildWithAI — Course landing + Google OAuth signup
FastAPI + Jinja2 + MongoDB Atlas + Authlib (Google)
"""
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth, OAuthError
from dotenv import load_dotenv

from user_agents import parse
import httpx
from database import db, init_indexes

load_dotenv()

# ─── Config ────────────────────────────────────────────────
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-prod")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="BuildWithAI")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─── Google OAuth ──────────────────────────────────────────
oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# Index creation: runs once, lazily (works on serverless where startup
# events don't reliably fire). Guarded so it only attempts once per instance.
_indexes_ready = False


async def ensure_indexes():
    global _indexes_ready
    if not _indexes_ready:
        try:
            await init_indexes()
            _indexes_ready = True
        except Exception:
            pass  # don't block requests if Atlas is briefly unreachable


def get_client_ip(request: Request) -> str:
    """Real IP — checks proxy headers first (Vercel/Nginx sit in front)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()   # first IP = original client
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"

async def get_location(ip: str) -> dict:
    if ip in ("unknown", "127.0.0.1") or ip.startswith("192.168") or ip.startswith("10."):
        return {"country": None, "region": None, "city": None}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city"
            )
            d = r.json()
            if d.get("status") != "success":
                return {"country": None, "region": None, "city": None}
            return {
                "country": d.get("country"),
                "region": d.get("regionName"),
                "city": d.get("city"),
            }
    except Exception:
        return {"country": None, "region": None, "city": None}
    
async def log_visit(request: Request):
    """Store a readable record of who hit the landing page."""
    ua_string = request.headers.get("user-agent", "")
    ua = parse(ua_string)  # from user_agents lib

    if ua.is_mobile:
        device_type = "Mobile"
    elif ua.is_tablet:
        device_type = "Tablet"
    elif ua.is_pc:
        device_type = "Desktop"
    elif ua.is_bot:
        device_type = "Bot"
    else:
        device_type = "Unknown"
    ip = get_client_ip(request)
    loc = await get_location(ip)
    await db.visitors.insert_one({
        "ip": ip,
        "country": loc["country"],
        "region": loc["region"],
        "city": loc["city"],
        "device_type": device_type,
        "browser": f"{ua.browser.family} {ua.browser.version_string}".strip(),
        "os": f"{ua.os.family} {ua.os.version_string}".strip(),
        "device": ua.device.family,          # e.g. "iPhone", "Samsung SM-G991B"
        "is_bot": ua.is_bot,
        "referrer": request.headers.get("referer", "direct"),
        "language": request.headers.get("accept-language", "").split(",")[0],
        "path": str(request.url.path),
        "visited_at": datetime.now(timezone.utc),
    })


# ─── Routes ────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    await ensure_indexes()
    try:
        await log_visit(request)          # don't let logging break the page
    except Exception:
        pass
    user = request.session.get("user")
    return templates.TemplateResponse(
    request,
    "index.html",
    {"user": user},
)

@app.get("/auth/login")
async def login(request: Request):
    redirect_uri = f"{BASE_URL}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/?error=auth_failed")

    info = token.get("userinfo")
    if not info:
        return RedirectResponse("/?error=no_userinfo")

    google_id = info["sub"]
    email = info.get("email")
    name = info.get("name", "")

    # Upsert minimal record on first sight
    existing = await db.signups.find_one({"google_id": google_id})
    if existing is None:
        await db.signups.insert_one({
            "google_id": google_id,
            "email": email,
            "name": name,
            "phone": None,
            "completed": False,
            "created_at": datetime.now(timezone.utc),
        })

    request.session["user"] = {
        "google_id": google_id,
        "email": email,
        "name": name,
    }

    # If they already completed profile, send straight to success
    if existing and existing.get("completed"):
        return RedirectResponse("/success")
    return RedirectResponse("/complete-profile")


@app.get("/complete-profile", response_class=HTMLResponse)
async def complete_profile_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/")
    # Pull existing record so the form can pre-fill name + phone when editing
    record = await db.signups.find_one({"google_id": user["google_id"]})
    return templates.TemplateResponse(
        request,
        "complete_profile.html",
        {"user": user, "record": record, "error": None},
    )


@app.post("/complete-profile")
async def complete_profile_submit(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/")

    # Basic phone validation (Pakistan-friendly, but flexible)
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if len(cleaned) < 10:
        record = await db.signups.find_one({"google_id": user["google_id"]})
        return templates.TemplateResponse(
            request,
            "complete_profile.html",
            {"user": user, "record": record,
             "error": "Please enter a valid phone number."},
        )

    await db.signups.update_one(
        {"google_id": user["google_id"]},
        {"$set": {
            "name": name.strip(),
            "phone": cleaned,
            "completed": True,
            "completed_at": datetime.now(timezone.utc),
        }},
    )
    request.session["user"]["name"] = name.strip()
    return RedirectResponse("/success", status_code=303)


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "success.html", {"user": user})


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


# ─── Simple admin export (protected by a token) ────────────
@app.get("/admin/signups")
async def admin_signups(token: str = ""):
    if token != os.getenv("ADMIN_TOKEN", "set-an-admin-token"):
        return {"error": "unauthorized"}
    rows = []
    async for s in db.signups.find({"completed": True}).sort("completed_at", -1):
        rows.append({
            "name": s.get("name"),
            "email": s.get("email"),
            "phone": s.get("phone"),
            "joined": s.get("completed_at").isoformat() if s.get("completed_at") else None,
        })
    return {"count": len(rows), "signups": rows}


@app.get("/admin/visitors")
async def admin_visitors(token: str = "", limit: int = 200):
    if token != os.getenv("ADMIN_TOKEN", "set-an-admin-token"):
        return {"error": "unauthorized"}

    # Recent visits (most recent first)
    visits = []
    async for v in db.visitors.find().sort("visited_at", -1).limit(limit):
        visits.append({
            "ip": v.get("ip"),
            "country": v.get("country"),
            "region": v.get("region"),
            "city": v.get("city"),
            "device_type": v.get("device_type"),
            "browser": v.get("browser"),
            "os": v.get("os"),
            "device": v.get("device"),
            "is_bot": v.get("is_bot"),
            "referrer": v.get("referrer"),
            "language": v.get("language"),
            "visited_at": v.get("visited_at").isoformat() if v.get("visited_at") else None,
        })

    # Quick rollups so you get the picture at a glance
    total = await db.visitors.count_documents({})
    humans = await db.visitors.count_documents({"is_bot": False})
    unique_ips = len(await db.visitors.distinct("ip"))

    # Top referrers (where traffic comes from)
    top_referrers = []
    async for r in db.visitors.aggregate([
        {"$group": {"_id": "$referrer", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]):
        top_referrers.append({"source": r["_id"], "count": r["count"]})

    # Device breakdown
    device_split = []
    async for d in db.visitors.aggregate([
        {"$group": {"_id": "$device_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]):
        device_split.append({"type": d["_id"], "count": d["count"]})

    return {
        "summary": {
            "total_visits": total,
            "human_visits": humans,
            "bot_visits": total - humans,
            "unique_ips": unique_ips,
        },
        "top_referrers": top_referrers,
        "device_breakdown": device_split,
        "recent_visits": visits,
    }
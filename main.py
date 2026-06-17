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


# ─── Routes ────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    await ensure_indexes()
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

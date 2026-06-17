# BuildWithAI — Course Signup Site

FastAPI + Jinja2 + MongoDB Atlas + Google OAuth.
Landing page (poster-based) → Google sign-in → collect name + WhatsApp number → "invitation shortly" page.

## Project structure

```
buildwithai/
├── main.py                  # FastAPI app + routes + OAuth
├── database.py              # MongoDB Atlas connection
├── requirements.txt
├── .env.example             # copy to .env and fill in
├── templates/
│   ├── index.html           # landing page
│   ├── complete_profile.html# name + phone form
│   └── success.html         # "invitation shortly"
└── static/                  # (empty for now)
```

## 1. Install

```bash
cd buildwithai
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Set up Google OAuth

1. Go to https://console.cloud.google.com → create/select a project
2. **APIs & Services → OAuth consent screen** → set up (External), add your email as a test user
3. **APIs & Services → Credentials → Create Credentials → OAuth Client ID**
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:8000/auth/callback`
     (add your prod URL too later: `https://yourdomain.com/auth/callback`)
4. Copy the **Client ID** and **Client Secret** into `.env`

## 3. Configure environment

```bash
cp .env.example .env
```

Then edit `.env`:
- `MONGODB_URL` → paste your full Atlas SRV connection string
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` → from step 2
- `SESSION_SECRET` → any long random string (`openssl rand -hex 32`)
- `ADMIN_TOKEN` → any secret for the export endpoint

**MongoDB Atlas note:** under **Network Access**, add your server's IP (or `0.0.0.0/0` while testing).

## 4. Run

```bash
uvicorn main:app --reload
```

Open http://localhost:8000

## 5. See who signed up

```
GET /admin/signups?token=YOUR_ADMIN_TOKEN
```

Returns name, email, phone, join time for everyone who completed signup. Use this to manually add them to the WhatsApp group.

## Data model (collection: `signups`)

```json
{
  "google_id": "unique google sub",
  "email": "user@gmail.com",
  "name": "Ahmad Khan",
  "phone": "03001234567",
  "completed": true,
  "created_at": "...",
  "completed_at": "..."
}
```

## Deploy (later)

- Any VPS with Nginx + your usual PM2/systemd setup works (same as your EC2 deploys).
- Set `BASE_URL=https://yourdomain.com` in `.env`
- Add `https://yourdomain.com/auth/callback` to Google authorized redirect URIs
- Run behind Nginx: `uvicorn main:app --host 127.0.0.1 --port 8000` + reverse proxy
```

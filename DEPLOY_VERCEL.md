# Deploying BuildWithAI to Vercel

## Files needed (already included)
- `vercel.json` — tells Vercel how to build/route the app
- `requirements.txt` — Vercel auto-installs these
- `main.py` — entry point (Vercel detects the `app` object)

## Steps

### 1. Push to GitHub
```bash
cd buildwithai
git init
git add .
git commit -m "BuildWithAI signup site"
# create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/buildwithai.git
git push -u origin main
```

> Make sure `.env` is NOT pushed — add a `.gitignore` with `.env` in it.
> Only `.env.example` should be in the repo.

### 2. Import to Vercel
1. Go to https://vercel.com → **Add New → Project**
2. Import your GitHub repo
3. Framework preset: **Other** (Vercel auto-detects Python)
4. Click **Deploy** (it'll fail the first time without env vars — that's fine)

### 3. Add Environment Variables
In Vercel → your project → **Settings → Environment Variables**, add each one:

| Key | Value |
|-----|-------|
| `SESSION_SECRET` | a long random string |
| `GOOGLE_CLIENT_ID` | your-id.apps.googleusercontent.com |
| `GOOGLE_CLIENT_SECRET` | your secret |
| `MONGODB_URL` | your full Atlas SRV link |
| `DB_NAME` | buildwithai |
| `ADMIN_TOKEN` | your chosen admin password |
| `BASE_URL` | https://YOUR-PROJECT.vercel.app |

> Set `BASE_URL` to your actual Vercel URL **after** the first deploy gives you one.
> Then redeploy.

### 4. Update Google OAuth redirect URI
In Google Cloud Console → Credentials → your OAuth client → **Authorized redirect URIs**, add:
```
https://YOUR-PROJECT.vercel.app/auth/callback
```

### 5. MongoDB Atlas network access
Atlas → **Network Access** → add IP `0.0.0.0/0`
(Vercel uses dynamic IPs, so you can't whitelist a single one. `0.0.0.0/0` + a strong DB password is the standard approach for serverless.)

### 6. Redeploy
Vercel → Deployments → **Redeploy** (so it picks up the env vars).

## ⚠️ Serverless gotchas to expect
- **Cold starts:** first request after idle may take 2-3 seconds. Normal.
- **Sessions are cookie-based** (already configured), so login persists fine across serverless invocations.
- **MongoDB connections:** motor opens a new connection per cold start. For low traffic (a course signup form) this is totally fine. If you ever scale big, switch to a VPS.

## Honestly though
For a course signup form with manual WhatsApp follow-up, Vercel works fine. But if you hit any serverless weirdness, your **EC2 + Nginx + uvicorn** setup (which you've done before) is rock solid and gives you the `/admin/signups` endpoint without cold-start delays.

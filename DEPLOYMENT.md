# Deployment Guide

TradeVed Backtester deploys as two services:

| Layer | Platform | What lives here |
|-------|----------|-----------------|
| **Frontend** (React/Vite) | **Vercel** | Static SPA, talks to the backend over HTTPS |
| **Backend** (FastAPI) | **Railway** | API + SQLite DB (analytics, feedback, backtests) |

Deploy the **backend first** — you need its public URL before you can configure the frontend.

---

## Part 1 — Backend on Railway

### 1. Create the service
1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `harshit-tradeved/Risk-Analytics-Backtester-and-Stress_Tester-TradeVed-`
3. After it imports, open the service → **Settings**:
   - **Root Directory:** *(leave empty — repo root)*. Since the July 2026 per-project
     restructure, the six project packages (`backtesting/`, `stress_testing/`, …) live at
     the repo root, so the build must include the whole repo. **If an existing service has
     Root Directory set to `backtester`, clear it** or the server will crash on import.
   - Build/start are auto-detected from the root `railway.json` + `Procfile` + `nixpacks.toml`
     (`cd backtester && python main.py`, which binds to Railway's `$PORT`; `nixpacks.toml`
     pins the Python provider so the root `package.json` — which exists only for npm
     workspace hoisting — doesn't make Nixpacks build it as a Node app)

### 2. Add a Volume (CRITICAL — without this all data is wiped on every redeploy)
1. Service → **Variables / Volumes** → **+ New Volume**
2. **Mount path:** `/data`

### 3. Set environment variables
Service → **Variables** → add:

| Variable | Value | Notes |
|----------|-------|-------|
| `ADMIN_TOKEN` | *(a long random secret)* | Generate one — see below. This is your admin key. |
| `DATABASE_URL` | `sqlite:////data/backtester.db` | **Four** slashes = absolute path into the mounted volume |

Generate a strong token (run locally):
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> Optional: `TV_*` and `FYERS_*` vars only if you need live TradingView/Fyers data fetching in production. The app works without them using Binance/yfinance.

### 4. Deploy & grab the URL
- Railway builds and deploys automatically. First build is slow (~5-8 min — heavy deps like `tvdatafeed`, `fyers-apiv3`, `kaleido`).
- Once live, go to **Settings → Networking → Generate Domain**.
- Copy the URL, e.g. `https://risk-analytics-production.up.railway.app`
- Verify: open `https://<your-url>/docs` — you should see the Swagger UI.

---

## Part 2 — Frontend on Vercel

### 1. Create the project
1. Go to [vercel.com](https://vercel.com) → **Add New → Project** → import the same GitHub repo
2. Configure:
   - **Root Directory:** *(leave empty — repo root)*. The per-project `frontend/` folders
     live at the repo root and are imported by the Vite app via aliases, so the build needs
     the whole repo. **If an existing project has Root Directory set to `backtester/frontend`,
     clear it** or those imports won't resolve.
   - **Framework Preset:** Other (the root `vercel.json` drives everything)
   - `vercel.json`: install runs `npm install` at the root (workspace hoisting), build runs
     `cd backtester/frontend && npm run build`, output is `backtester/frontend/dist`

### 2. Set the environment variable
Project → **Settings → Environment Variables** → add:

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | `https://<your-railway-url>.up.railway.app` *(no trailing slash)* |

> This is baked in at build time. If you change it later, you must **redeploy** the frontend.

### 3. Deploy
- Click **Deploy**. Vercel builds the SPA and gives you a URL like `https://tradeved-backtester.vercel.app`.

---

## Part 3 — Accessing the Admin Dashboard

The admin dashboard is **token-gated and hidden** by default — no admin tab appears for normal testers.

1. Visit your Vercel URL **once** with the token as a query param:
   ```
   https://<your-site>.vercel.app/?admin=<your-ADMIN_TOKEN>
   ```
2. The token is validated against the backend (`/api/admin/ping`), stored in `localStorage`, and **stripped from the URL immediately** so it's never visible or shareable.
3. The 🔒 **Admin** pill now appears in the top nav and stays until you clear browser data.

If the token is wrong, no admin tab appears and the stored token is cleared.

---

## Redeploys

- **Push to the branch connected on each platform** → both auto-redeploy.
- Backend redeploys keep all data **only because of the `/data` volume** — never remove it.
- Frontend env var changes (`VITE_API_BASE_URL`) require a manual redeploy to take effect.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Frontend loads but every API call fails (CORS / network) | `VITE_API_BASE_URL` wrong or missing — check it points at the Railway URL with no trailing slash, then redeploy frontend |
| Admin tab won't appear | Backend not reachable, or `ADMIN_TOKEN` mismatch between the URL you used and Railway's env var |
| Analytics/feedback reset after a deploy | Volume not mounted at `/data`, or `DATABASE_URL` not pointing into it (needs 4 slashes) |
| Railway build fails on `tvdatafeed` | Transient git fetch — retry the deploy |
| `502`/`Application failed to respond` on Railway | App not binding to `$PORT` — confirm `Procfile`/`railway.json` run `python main.py` (which reads `PORT`) |

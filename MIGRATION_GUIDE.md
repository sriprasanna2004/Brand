# BrandIQ — Migration Guide (Kiro → Windsurf/Antigravity)

## Why the Permission Error Happens

Windsurf/Antigravity chokes on:
1. **`.venv/` inside the workspace** — thousands of files with locked permissions
2. **`__pycache__/`** — binary cache files that confuse indexers
3. **`.git/`** — large object store that IDE tries to index
4. **Duplicate folder structure** — `brandiq/src/` and `brandiq/brandiq/src/` confuse the IDE

## The Clean Project

Open this folder in Windsurf: `c:\Users\acer\Documents\BrandIQ_CLEAN\`

It contains only source code — no venvs, no caches, no git history.

## Project Structure (Clean)

```
BrandIQ_CLEAN/
├── main.py                     ← FastAPI app entry point
├── alembic.ini                 ← DB migration config
├── supervisord.conf            ← Process manager (Railway)
├── Dockerfile                  ← Container build
├── docker-compose.yml          ← Local dev
├── requirements-railway.txt    ← Production dependencies
├── requirements.txt            ← Dashboard dependencies
├── .env.example                ← Environment variable template
├── adaptiq_landing.html        ← Adaptiq trial landing page
├── privacy.html                ← Privacy policy page
├── src/
│   ├── agents/                 ← AI agents (Groq LLM)
│   ├── crews/                  ← Agent orchestration
│   ├── tools/                  ← Instagram, WhatsApp, Telegram, etc.
│   ├── scheduler/              ← Celery tasks + APScheduler crons
│   ├── dashboard/              ← Streamlit dashboard
│   ├── models.py               ← SQLAlchemy DB models
│   ├── database.py             ← DB connection
│   └── redis_client.py         ← Redis connection
└── migrations/
    └── versions/               ← Alembic migration files
```

## Setup in Windsurf

### 1. Open the clean folder
```
File → Open Folder → BrandIQ_CLEAN
```

### 2. Create virtual environment (outside the project folder)
```powershell
python -m venv C:\venvs\brandiq
C:\venvs\brandiq\Scripts\activate
pip install -r requirements-railway.txt
```

**Important:** Keep the venv OUTSIDE the project folder to avoid permission issues.

### 3. Configure Windsurf Python interpreter
- `Ctrl+Shift+P` → "Python: Select Interpreter"
- Choose `C:\venvs\brandiq\Scripts\python.exe`

### 4. Set up environment variables
```powershell
Copy-Item .env.example .env
# Edit .env with your actual values
```

### 5. Run locally
```powershell
# Terminal 1 — API
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Celery worker
celery -A src.scheduler.tasks worker --loglevel=info

# Terminal 3 — Dashboard
streamlit run src/dashboard/app.py
```

## Deployed App (Railway)

The app is already live — you don't need to run it locally unless developing.

| Service | URL |
|---|---|
| API | https://hospitable-comfort-production.up.railway.app |
| Dashboard | https://brandiq-cuvssqepgz44ysxb6ckof9.streamlit.app |
| Landing page | https://hospitable-comfort-production.up.railway.app/adaptiq |
| Privacy policy | https://hospitable-comfort-production.up.railway.app/privacy |

## Deploying Changes

```powershell
# From BrandIQ_CLEAN or the original brandiq/brandiq/ folder
git add .
git commit -m "your change"
git push origin main
railway up --detach
```

## Key Environment Variables Required

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL (asyncpg) |
| `DATABASE_URL_SYNC` | PostgreSQL (psycopg2, for Celery) |
| `REDIS_URL` | Redis broker |
| `GROQ_API_KEY` | LLM for all agents |
| `META_ACCESS_TOKEN` | Instagram/Facebook API |
| `TELEGRAM_BOT_TOKEN` | Telegram bot |
| `R2_*` | Cloudflare R2 image storage |

## What NOT to do in Windsurf

- ❌ Don't open `BrandIQ_copy/` — it has nested venvs that cause permission errors
- ❌ Don't put `.venv/` inside the project folder
- ❌ Don't open `brandiq/brandiq/` directly — use `BrandIQ_CLEAN/` instead

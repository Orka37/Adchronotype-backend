# ADChronotype API

FastAPI backend for the ADChronotype brain health prediction app.

## Stack
- FastAPI 0.111 + Uvicorn
- PostgreSQL + SQLAlchemy
- JWT auth (access 60 min + refresh 30 days)
- XGBoost prediction model
- Rate limiting via slowapi

## Deploy to Render (recommended — free tier works)

1. Push this folder to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects the `render.yaml` — click **Apply**
5. It creates the PostgreSQL database and web service automatically
6. Set these environment variables in Render dashboard:
   - `JWT_SECRET_KEY` — generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
   - `APP_ENV` → `production`
   - `DATABASE_URL` → auto-filled by Render from the linked database

7. After first deploy, run migrations:
   ```
   # In Render dashboard → Shell tab
   alembic upgrade head
   ```
   Then copy the `ml_model.pkl` file into the root of your repo.

8. Your API is live at:
   `https://adchronotype-api.onrender.com`

## Deploy to Railway (alternative)

1. Install Railway CLI: `npm install -g @railway/cli`
2. `railway login`
3. `railway init` (inside this folder)
4. `railway add` → add a PostgreSQL plugin
5. Set env vars: `railway variables set JWT_SECRET_KEY=... APP_ENV=production FRONTEND_ORIGINS=https://your-frontend-domain.com`
6. `railway up`

Railway runs `alembic upgrade head` before starting the API, using the command in `railway.json`.

## Local development

```bash
cp .env.example .env
# fill in your local postgres DATABASE_URL and a JWT_SECRET_KEY

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API docs available at http://localhost:8000/docs in development.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `JWT_SECRET_KEY` | ✅ | Random secret, min 32 chars |
| `JWT_ALGORITHM` | default HS256 | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | default 60 | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | default 30 | Refresh token lifetime |
| `APP_ENV` | default development | Set to `production` on server |
| `FRONTEND_ORIGINS` | production | Comma-separated allowed frontend origins |
| `RUN_MIGRATIONS_ON_STARTUP` | default false | Optional fallback for running migrations during app startup |

## Production checklist

- Set `APP_ENV=production`.
- Set a stable `JWT_SECRET_KEY`; changing it logs out every user.
- Set `FRONTEND_ORIGINS` to the deployed frontend URL.
- Run `alembic upgrade head` before the API accepts traffic.
- Confirm `/health` returns `{"status":"ok","database":"ok"}`.
- Run `pytest -q` before deployment.

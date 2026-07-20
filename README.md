# ADChronotype API

FastAPI backend for the ADChronotype brain health prediction app.

## Stack
- FastAPI 0.111 + Uvicorn
- PostgreSQL + SQLAlchemy
- JWT auth (access 60 min + refresh 30 days)
- XGBoost prediction model
- Rate limiting via slowapi

## Deploy to Railway

1. Push this folder to GitHub.
2. In Railway, connect the GitHub repository to the backend service.
3. Attach a PostgreSQL database service.
4. Set the required environment variables in the Railway service settings.
5. Deploy the service.

Railway runs database migrations before starting the API by using the command in `railway.json`.

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
| `FRONTEND_APP_URL` | password reset | Public frontend URL used in password reset email links |
| `RESEND_API_KEY` | password reset email | Resend API key for sending password reset emails |
| `PASSWORD_RESET_FROM_EMAIL` | password reset email | Verified sender, for example `ADChronotype <onboarding@resend.dev>` |
| `RUN_MIGRATIONS_ON_STARTUP` | default false | Optional fallback for running migrations during app startup |

## Production checklist

- Set `APP_ENV=production`.
- Set a stable `JWT_SECRET_KEY`; changing it logs out every user.
- Set `FRONTEND_ORIGINS` to the deployed frontend URL.
- Set `FRONTEND_APP_URL` to the deployed frontend URL.
- Set `RESEND_API_KEY` and `PASSWORD_RESET_FROM_EMAIL` before testing password reset emails.
- Run `alembic upgrade head` before the API accepts traffic.
- Confirm `/health` returns `{"status":"ok","database":"ok"}`.
- Run `pytest -q` before deployment.

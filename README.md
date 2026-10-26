# ADChronotype API

Python FastAPI backend for authentication, research similarity scores, sleep logs and caregiver workflows. PostgreSQL stores application records through SQLAlchemy. Scores are research outputs, not clinical diagnoses.

## Architecture

```mermaid
flowchart LR
    App[React Native / Expo client] <-->|HTTPS JSON + JWT| API[FastAPI routers]
    API <-->|SQLAlchemy| DB[(PostgreSQL)]
    API --> Predict[POST /predictions]
    Predict --> Model[ml_model.pkl + SHAP]
    Model -->|Score and contributions| Predict
    Predict -->|Save prediction| DB
    Predict -->|Response| API
    API --> Care[Caregiver recommendation logic]
```

The model executes inside the backend process. The current `/predictions` flow uses 20 encoded features, normalization and legacy score offsets, and saves prediction history. Caregiver recommendations use separate application logic; they are not model outputs.

V2 development lives on the `test` branch. Its seven-feature `/api/v1/predict_similarity` endpoint is not present on `main`; its model artifact and integration remain separate work. These instructions describe the current `main` branch.

## Run locally

Use Python 3.11 (matching `runtime.txt`), PostgreSQL and a virtual environment. Run commands from this repository root.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Create a `.env` file in the repository root with the following values. Replace the signing-secret placeholder with the generated value and set `DATABASE_URL` for your development database. Do not commit `.env`.

```dotenv
DATABASE_URL=postgresql+psycopg2://adc:adc_local@localhost:5432/adchronotype
JWT_SECRET_KEY=replace-with-the-generated-secret
APP_ENV=development
FRONTEND_ORIGINS=http://localhost:8081
FRONTEND_APP_URL=http://localhost:8081
RUN_MIGRATIONS_ON_STARTUP=false
```

Optional Docker setup, using the local credentials above:

```bash
docker run --name adc-postgres -e POSTGRES_USER=adc -e POSTGRES_PASSWORD=adc_local -e POSTGRES_DB=adchronotype -p 5432:5432 -d postgres:16
```

For an existing container use `docker start adc-postgres`. Keep development credentials local.

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs for development Swagger UI. Register/login through `/auth`, then use the access token in Swagger's Authorize control. `/health` checks API/database connectivity, not model inference. The existing `ml_model.pkl` must be present for application import. On macOS, XGBoost may require the OpenMP runtime (`brew install libomp`).

## Configuration

Required: `DATABASE_URL`, `JWT_SECRET_KEY`. Use the local `.env` example above.

- `APP_ENV=production` disables Swagger/ReDoc.
- `FRONTEND_ORIGINS`: comma-separated browser origins; use your frontend's actual port/domain.
- `FRONTEND_APP_URL`: frontend URL for password-reset links.
- `GOOGLE_WEB_CLIENT_ID`: Google authentication audience.
- `RESEND_API_KEY`, `PASSWORD_RESET_FROM_EMAIL`: password-reset email delivery.
- `RUN_MIGRATIONS_ON_STARTUP`: defaults to false; Railway already migrates before starting.
- `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`: default 60 and 30.

## Code map

- `app/main.py`: application setup, router registration, CORS and startup checks.
- `app/routers/`: HTTP routes and authorization.
- `app/services/`: inference and caregiver recommendation logic.
- `app/schemas.py`, `app/models.py`: API schemas and database models.
- `app/core/`: settings, authentication and dependencies.
- `migrations/`: Alembic database changes.
- `tests/`: API and service tests.

## Tests

Configure a dedicated test database, never production, and install `requirements-dev.txt`. Run from the repository root:

```bash
python -m pytest -q
```

The suite includes API, Google authentication, sleep-rating and caregiver recommendation tests. Tests alone do not establish model accuracy or successful deployed inference. Before rollout, test a real authenticated prediction and confirm it appears in history.

## Railway

Connect the repository and PostgreSQL service; set the environment variables above with production values. `railway.json` runs `alembic upgrade head` then Uvicorn on Railway's `PORT`. Deployments require the correct model artifacts. Check `/health` and exercise authenticated prediction separately.

## License

See [LICENSE](LICENSE).

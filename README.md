# FedExSucks

Private FedEx-first package tracker for Norm.

Scope for v1:
- own packages only
- FedEx API-backed
- private site
- alerts on meaningful status changes

## Production direction

This project is being ported mostly as-is into a real VPS service instead of rewritten from scratch.

Minimum production stance:
- Postgres-first for production
- env-driven Django settings
- `DEBUG=false` in production
- repo-local deploy script

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

## VPS deploy scaffold

A first-pass deploy helper lives at:

```bash
./scripts/deploy-fedexsucks-vps.sh
```

Expected on the VPS:
- project checkout at `/home/norm/sites/fedexsucks`
- `.env` present on the server
- systemd service named `fedexsucks.service`

## Internal API

FedExSucks now exposes a small bearer-protected internal API intended for Docstore or other trusted internal callers.

Expected auth header:

```bash
Authorization: Bearer $INTERNAL_API_KEY
```

Endpoints:

- `GET /api/internal/health/`
- `GET /api/internal/packages/search/?q=<query>&limit=10`
- `GET /api/internal/packages/<tracking_number>/`
- `GET /api/internal/packages/<tracking_number>/latest-status/`

This API is intentionally simple and private-facing. It should stay behind app auth, host-level controls, and an internal shared secret.

## Next likely steps

- move live data to Postgres
- expand Docstore-side shipping workflows after the first integration is live
- later decide whether to rename the project/repo after the first successful port

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

## Next likely steps

- move live data to Postgres
- add a small authenticated API for Docstore integration
- later decide whether to rename the project/repo after the first successful port

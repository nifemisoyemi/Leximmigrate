# LexImmigrate

**Guided U.S. immigration, with as much attorney support as you choose.**

LexImmigrate is a client platform for **Yohana Saucedo Attorney Law**. Clients move
through a guided, step-by-step immigration process and decide how much attorney
involvement they want — from do-it-yourself, to attorney review, to full legal
representation. The platform launches with **N-400 (Naturalization)** and is built so
that additional application types can be added as data, not new code.

> **Confidential / proprietary.** This repository and its contents are the property of
> Yohana Saucedo Attorney Law. It is not open source. The platform is designed to hold
> sensitive personal information; treat the codebase and all credentials accordingly.

---

## Status

Phase 1 (MVP) — in active development. One application type (N-400), three package
tiers (DIY, Enhanced, Full Service), the full client journey from eligibility
questionnaire to decision guidance, and staff tooling via a customized Django Admin.

## Tech stack

- **Backend:** Django 5.2 LTS (Python 3.13), server-rendered
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js
- **Database:** PostgreSQL
- **Auth:** Django sessions + TOTP two-factor (`django-two-factor-auth`)
- **Payments:** Stripe Checkout + webhooks
- **Document storage:** DigitalOcean Spaces (S3-compatible) with signed URLs
- **Background jobs:** django-rq + Redis (virus scanning, email, webhooks)
- **Virus scanning:** ClamAV
- **Email:** Postmark (`django-anymail`)
- **Scheduling:** Cal.com (booking) synced into the firm's Monday.com board
- **Audit log:** `django-auditlog`
- **Monitoring / CI:** Sentry + GitHub Actions
- **Hosting:** DigitalOcean Droplet behind Cloudflare

## Project structure

```
Leximmigrate/
├── config/            # Django project (settings, urls, wsgi)
├── accounts/          # Custom User model, auth
├── catalog/           # Application types, tiers, packages, workflow & document templates, questionnaire
├── cases/             # Leads, cases, documents, consultations, notes, status updates, payments
├── templates/         # Server-rendered HTML
├── static/            # CSS/JS assets
├── .env               # Local secrets (NEVER committed)
├── .env.example       # Template for .env
├── requirements.txt
└── manage.py
```

## Local development setup

Requires **Python 3.13** and **PostgreSQL** running locally.

```bash
# 1. Clone and enter
git clone https://github.com/<your-username>/Leximmigrate.git
cd Leximmigrate

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Environment variables
copy .env.example .env        # Windows  (cp on macOS/Linux)
# then edit .env: set SECRET_KEY, DATABASE_URL

# 5. Database
python manage.py migrate
python manage.py createsuperuser

# 6. Run
python manage.py runserver
# visit http://127.0.0.1:8000/  and  http://127.0.0.1:8000/admin/
```

## Environment variables

| Variable        | Purpose                                        |
|-----------------|------------------------------------------------|
| `SECRET_KEY`    | Django cryptographic secret                    |
| `DEBUG`         | `True` locally, `False` in staging/production  |
| `ALLOWED_HOSTS` | Comma-separated hostnames                       |
| `DATABASE_URL`  | `postgres://user:pass@host:port/dbname`        |

Secrets live only in `.env` (git-ignored) locally, and in the host's environment in
staging/production. They are never committed.

## Environments

- **Development** — your machine.
- **Staging** — private DigitalOcean deployment for milestone review.
- **Production** — live deployment on the firm's accounts.

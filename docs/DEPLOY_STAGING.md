# LexImmigrate — Staging Deployment Guide
Target: https://staging.leximmigrate.com on a DigitalOcean droplet, behind
Cloudflare, password-walled, Stripe in test mode.

Conventions: `local %` = your Mac terminal · `server $` = SSH'd into the droplet.
Replace ALL-CAPS placeholders. Never paste secrets into chat.

======================================================================
PHASE 1 — Create the droplet (DigitalOcean dashboard, ~10 min)
======================================================================
1. digitalocean.com → Create → Droplets.
   - Region: New York (NYC3) — closest reliable choice for Texas.
   - Image: Ubuntu 24.04 LTS.
   - Size: Basic → Regular → $12/mo (2 GB RAM). $6 is too tight for
     Postgres + Django; upgrade later is one click.
   - Authentication: SSH key. On your Mac, if you have no key yet:
       local %  ssh-keygen -t ed25519 -C "leximmigrate-staging"
       local %  cat ~/.ssh/id_ed25519.pub
     Paste that public key into DigitalOcean's "New SSH key" box.
   - Hostname: leximmigrate-staging.
2. Create. Note the droplet's public IP: DROPLET_IP.
3. Test:  local %  ssh root@DROPLET_IP      (answer "yes" to the fingerprint)

======================================================================
PHASE 2 — Bootstrap the server (~15 min)
======================================================================
server $  apt update && apt upgrade -y
server $  apt install -y software-properties-common
server $  add-apt-repository -y ppa:deadsnakes/ppa && apt update
server $  apt install -y python3.13 python3.13-venv python3.13-dev \
            postgresql postgresql-contrib nginx git build-essential libpq-dev \
            apache2-utils

# A non-root user to run the app (never run Django as root)
server $  adduser --disabled-password --gecos "" deploy
server $  usermod -aG sudo deploy
server $  mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ \
            && chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh

# Firewall: only SSH + web
server $  ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable

# Postgres database + user (pick a REAL generated password — not "changeme")
server $  sudo -u postgres psql -c "CREATE USER leximmigrate WITH PASSWORD 'DB_PASSWORD';"
server $  sudo -u postgres psql -c "CREATE DATABASE leximmigrate OWNER leximmigrate;"

# Switch to the deploy user for everything app-related from here
server $  su - deploy

======================================================================
PHASE 3 — Install the app (~15 min)
======================================================================
server $  git clone https://github.com/nifemisoyemi/Leximmigrate.git
server $  cd Leximmigrate
server $  python3.13 -m venv .venv && source .venv/bin/activate
server $  pip install -r requirements.txt

# The .env — create it on the server with nano. Staging values:
server $  nano .env
------------------------------------------------------------------
SECRET_KEY=GENERATE_A_NEW_ONE      # python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DEBUG=False
ALLOWED_HOSTS=staging.leximmigrate.com
CSRF_TRUSTED_ORIGINS=https://staging.leximmigrate.com
DATABASE_URL=postgres://leximmigrate:DB_PASSWORD@127.0.0.1:5432/leximmigrate
MONDAY_API_TOKEN=...               # same as local
MONDAY_BOARD_ID=18424209220
STRIPE_PUBLISHABLE_KEY=pk_test_... # TEST keys — staging never touches live
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=              # filled in Phase 5
ACUITY_OWNER_ID=40327942
POSTMARK_SERVER_TOKEN=...          # same as local
------------------------------------------------------------------
(Ctrl+O, Enter, Ctrl+X)

server $  python manage.py migrate
server $  python manage.py seed_catalog
server $  python manage.py seed_questionnaire_v2
server $  python manage.py seed_document_categories
server $  python manage.py createsuperuser
server $  python manage.py collectstatic --noinput
server $  mkdir -p media && exit          # back to root for system config

======================================================================
PHASE 4 — Run it: gunicorn + nginx + HTTPS (~25 min)
======================================================================
# --- gunicorn as a system service ---
server $  nano /etc/systemd/system/leximmigrate.service
------------------------------------------------------------------
[Unit]
Description=LexImmigrate (gunicorn)
After=network.target

[Service]
User=deploy
Group=www-data
WorkingDirectory=/home/deploy/Leximmigrate
EnvironmentFile=/home/deploy/Leximmigrate/.env
ExecStart=/home/deploy/Leximmigrate/.venv/bin/gunicorn config.wsgi:application \
  --workers 3 --bind unix:/run/leximmigrate.sock --timeout 60
Restart=always
RuntimeDirectory=leximmigrate

[Install]
WantedBy=multi-user.target
------------------------------------------------------------------
server $  systemctl daemon-reload && systemctl enable --now leximmigrate
server $  systemctl status leximmigrate      # want "active (running)"

# --- Staging password wall (Yohana's login to the whole site) ---
server $  htpasswd -c /etc/nginx/.htpasswd yohana    # prompts for a password
server $  htpasswd /etc/nginx/.htpasswd nifemi        # (no -c the 2nd time)

# --- Cloudflare Origin Certificate (free, 15-year, no renewals) ---
# Cloudflare dashboard → leximmigrate.com → SSL/TLS → Origin Server →
# Create Certificate → defaults (RSA, *.leximmigrate.com + leximmigrate.com,
# 15 years) → Create. Copy the two text blocks into these files:
server $  mkdir -p /etc/ssl/cloudflare
server $  nano /etc/ssl/cloudflare/origin.pem      # paste "Origin Certificate"
server $  nano /etc/ssl/cloudflare/origin.key      # paste "Private Key"
server $  chmod 600 /etc/ssl/cloudflare/origin.key
# Then Cloudflare → SSL/TLS → Overview → set mode to "Full (strict)".

# --- nginx site ---
server $  nano /etc/nginx/sites-available/leximmigrate
------------------------------------------------------------------
server {
    listen 80;
    server_name staging.leximmigrate.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name staging.leximmigrate.com;

    ssl_certificate     /etc/ssl/cloudflare/origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/origin.key;

    client_max_body_size 20M;    # matches the 15MB upload cap + headroom

    # Password wall for the whole staging site...
    auth_basic           "LexImmigrate staging";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location /static/ {
        alias /home/deploy/Leximmigrate/staticfiles/;
    }
    location /media/ {
        alias /home/deploy/Leximmigrate/media/;
    }

    # ...EXCEPT the Stripe webhook — Stripe can't type a password.
    location /stripe/webhook/ {
        auth_basic off;
        include proxy_params;
        proxy_pass http://unix:/run/leximmigrate.sock;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/leximmigrate.sock;
    }
}
------------------------------------------------------------------
server $  ln -s /etc/nginx/sites-available/leximmigrate /etc/nginx/sites-enabled/
server $  rm -f /etc/nginx/sites-enabled/default
server $  nginx -t && systemctl reload nginx
server $  chmod 755 /home/deploy       # lets nginx read static/media

# --- DNS (Cloudflare) ---
# DNS → Add record: Type A, Name staging, IPv4 DROPLET_IP, Proxy ON (orange).
# (Orange is correct HERE — this is a website, not mail. Cloudflare handles
# the public HTTPS; the origin cert secures Cloudflare→droplet.)

# Test: open https://staging.leximmigrate.com → browser password prompt →
# your htpasswd login → the homepage. 

======================================================================
PHASE 5 — Stripe webhook for staging (~5 min)
======================================================================
Staging has no CLI tunnel — Stripe calls the public URL directly.
1. Stripe dashboard (TEST mode) → Developers → Webhooks → Add endpoint.
   URL: https://staging.leximmigrate.com/stripe/webhook/
   Events: checkout.session.completed
2. Copy the endpoint's "Signing secret" (whsec_...).
3. server $  su - deploy && cd Leximmigrate && nano .env
   → set STRIPE_WEBHOOK_SECRET=whsec_...   → save → exit
4. server $  sudo systemctl restart leximmigrate
5. Test purchase on staging with 4242 4242 4242 4242 → Stripe dashboard
   → Webhooks → the endpoint shows a 200 → case created, receipt emailed.

======================================================================
PHASE 6 — Deploying updates (every time, forever)
======================================================================
server $  nano /home/deploy/deploy.sh
------------------------------------------------------------------
#!/bin/bash
set -e
cd /home/deploy/Leximmigrate
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt --quiet
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart leximmigrate
echo "Deployed $(git rev-parse --short HEAD)"
------------------------------------------------------------------
server $  chmod +x /home/deploy/deploy.sh

Workflow from now on: commit + push locally, then
  local %  ssh deploy@DROPLET_IP ./deploy.sh
One command. (GitHub Actions can run this automatically on push later.)

======================================================================
Troubleshooting
======================================================================
- 502 Bad Gateway → gunicorn isn't running:
    journalctl -u leximmigrate -n 50      (shows the Python error)
- Static/CSS missing → collectstatic didn't run, or chmod 755 /home/deploy skipped
- "DisallowedHost" → ALLOWED_HOSTS in .env doesn't match the domain
- CSRF errors on forms → CSRF_TRUSTED_ORIGINS missing the https:// prefix
- Cloudflare 521/526 → origin cert files wrong, or SSL mode not Full (strict)
- Any .env change → sudo systemctl restart leximmigrate (settings snapshot rule)
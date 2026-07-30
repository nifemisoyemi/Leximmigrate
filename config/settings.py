"""
Django settings for LexImmigrate (config project).

Env-driven: secrets and per-environment values are read from environment
variables (loaded from .env locally via django-environ). No secrets in code.

Later we'll split this into settings/dev.py, settings/staging.py, settings/prod.py.
One env-driven file is enough while we scaffold.
"""

from pathlib import Path
import environ

# BASE_DIR is the repo root (folder containing manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment ---------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
MONDAY_API_TOKEN = env("MONDAY_API_TOKEN", default="")
MONDAY_BOARD_ID = env("MONDAY_BOARD_ID", default="")

# --- Applications --------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "accounts",
    "catalog",
    "cases",
    "quiz",
    "checkout",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ------------------------------------------------------------
# Parses DATABASE_URL from the environment (e.g. postgres://user:pass@host:port/db).
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# --- Custom user model ---------------------------------------------------
# MUST be set before the first migration. Do not change after migrating.
AUTH_USER_MODEL = "accounts.User"

# --- Password validation -------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"   # firm is based in Texas
USE_I18N = True
USE_TZ = True

# --- Static & media ------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"      # local only; DO Spaces takes over in Milestone 2

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Login redirects -----------------------------------------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# --- Email config --------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "LexImmigrate <noreply@leximmigrate.com>"
FIRM_NOTIFICATION_EMAIL = "leads@leximmigrate.test"
from __future__ import annotations

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure-change-me"),
    ALLOWED_HOSTS=(list, ["*"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    APP_PREFIX=(str, "e2e_chat"),
    USE_MANIFEST_STATIC=(bool, False),
    MONGODB_URI=(str, "mongodb://127.0.0.1:27017"),
    MONGODB_DB_NAME=(str, "pulsepair_chat"),
    SESSION_COOKIE_AGE_SECONDS=(int, 60 * 60 * 24),
    EMAIL_HOST=(str, "smtp.gmail.com"),
    EMAIL_PORT=(int, 587),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    EMAIL_USE_TLS=(bool, True),
    DEFAULT_FROM_EMAIL=(str, "PulsePair Security <no-reply@pulsepair.local>"),
    SIGNUP_OTP_TTL_SECONDS=(int, 10 * 60),
    SIGNUP_OTP_RESEND_COOLDOWN_SECONDS=(int, 45),
    SIGNUP_OTP_MAX_ATTEMPTS=(int, 6),
    GOOGLE_OAUTH_CLIENT_ID=(str, ""),
    GOOGLE_OAUTH_CLIENT_SECRET=(str, ""),
    GOOGLE_OAUTH_SCOPES=(list, ["openid", "email", "profile"]),
    GOOGLE_OAUTH_AUTH_URI=(str, "https://accounts.google.com/o/oauth2/v2/auth"),
    GOOGLE_OAUTH_TOKEN_URI=(str, "https://oauth2.googleapis.com/token"),
    GOOGLE_OAUTH_USERINFO_URI=(str, "https://openidconnect.googleapis.com/v1/userinfo"),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
if not [origin for origin in CSRF_TRUSTED_ORIGINS if origin]:
    if os.getenv("RENDER"):
        CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"]

INSTALLED_APPS = [
    "daphne",
    "channels",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "chatcore",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "chatcore.middleware.IdentityMiddleware",
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
            ],
        },
    },
]

ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.dummy",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_AGE = env("SESSION_COOKIE_AGE_SECONDS")
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_MANIFEST_STATIC = env("USE_MANIFEST_STATIC")
APP_PREFIX = env("APP_PREFIX")
MONGODB_URI = env("MONGODB_URI")
MONGODB_DB_NAME = env("MONGODB_DB_NAME")
SIGNUP_OTP_TTL_SECONDS = env("SIGNUP_OTP_TTL_SECONDS")
SIGNUP_OTP_RESEND_COOLDOWN_SECONDS = env("SIGNUP_OTP_RESEND_COOLDOWN_SECONDS")
SIGNUP_OTP_MAX_ATTEMPTS = env("SIGNUP_OTP_MAX_ATTEMPTS")

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")

GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET")
GOOGLE_OAUTH_SCOPES = env("GOOGLE_OAUTH_SCOPES")
GOOGLE_OAUTH_AUTH_URI = env("GOOGLE_OAUTH_AUTH_URI")
GOOGLE_OAUTH_TOKEN_URI = env("GOOGLE_OAUTH_TOKEN_URI")
GOOGLE_OAUTH_USERINFO_URI = env("GOOGLE_OAUTH_USERINFO_URI")

if USE_MANIFEST_STATIC:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

# No Redis cache usage; websocket fanout is process-local.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

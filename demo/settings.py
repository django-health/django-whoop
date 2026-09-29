"""Minimal Django settings for the bundled demo project.

Demonstrates installing both ``healthdatamodel`` (storage) and ``whoop``
(this app) alongside Django's built-in apps.

WHOOP OAuth credentials are read from environment variables so you can run
the demo without editing this file:

* ``WHOOP_CLIENT_ID`` (from the WHOOP developer dashboard)
* ``WHOOP_CLIENT_SECRET``
* ``WHOOP_REDIRECT_URI`` (must EXACTLY match a redirect URL registered in
  the WHOOP developer dashboard, including the trailing slash)
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-demo-key-do-not-use-in-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "healthdatamodel",
    "whoop",
    "demo",
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

ROOT_URLCONF = "demo.urls"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

WHOOP_CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "")
WHOOP_CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
WHOOP_REDIRECT_URI = os.environ.get(
    "WHOOP_REDIRECT_URI",
    "http://localhost:8000/whoop/callback/",
)

# Where whoop.views.callback / disconnect redirect to. Library default is
# /admin/; for the demo we want the user-facing homepage.
WHOOP_CONNECT_SUCCESS_URL = "/"

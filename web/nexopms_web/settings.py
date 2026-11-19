"""
Configuración de Django para NexoPMS Web.
Reutiliza la base de datos MySQL 'nexopms_db' a través de ConexionDB (conexion.py)
y almacena la sesión de usuario en cookies firmadas para no requerir tablas extra.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SECRET_KEY = "nexopms-hotel-los-arrayanes-dev-secret-key-change-in-prod"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pms",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nexopms_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nexopms_web.wsgi.application"

# Sesiones firmadas en cookie (no requiere migraciones SQLite; toda la persistencia está en MySQL vía ConexionDB)
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

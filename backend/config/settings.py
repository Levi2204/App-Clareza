import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-development-only-financas')
DEBUG = os.environ.get('DEBUG', '1') == '1'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver', 'backend']
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'rest_framework', 'corsheaders', 'finance']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'corsheaders.middleware.CorsMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware']
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
from .storage import data_directory
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': data_directory() / 'clareza.sqlite3', 'OPTIONS': {'timeout': 30, 'transaction_mode': 'IMMEDIATE'}}}
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Fortaleza'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173']
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'], 'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'], 'COERCE_DECIMAL_TO_STRING': True, 'EXCEPTION_HANDLER': 'finance.api.exception_handler'}
# Single-user mode is explicit, loopback-only; disable it before exposing the API.
LOCAL_MODE = os.environ.get('LOCAL_MODE', '1') == '1'
DESKTOP_TOKEN = os.environ.get('CLAREZA_DESKTOP_TOKEN', '')
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = ['finance.renderers.MoneyRenderer', 'rest_framework.renderers.BrowsableAPIRenderer']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]

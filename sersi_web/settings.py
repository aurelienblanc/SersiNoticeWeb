import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.environ.get('SERSI_DATA_DIR', BASE_DIR / 'runtime'))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
DEBUG = os.environ.get('SERSI_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('SERSI_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SERSI_SECRET_KEY est obligatoire en production.')
    secret_file = RUNTIME_DIR / '.development-secret'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(64), encoding='utf-8')
    SECRET_KEY = secret_file.read_text(encoding='utf-8')

ALLOWED_HOSTS = list(dict.fromkeys(['localhost', '127.0.0.1', '[::1]', *os.environ.get('SERSI_ALLOWED_HOSTS', '').split(',')]))
CSRF_TRUSTED_ORIGINS = list(filter(None, os.environ.get('SERSI_TRUSTED_ORIGINS', '').split(',')))
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'catalogue',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'catalogue.maintenance_middleware.MaintenanceMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'sersi_web.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'sersi_web.wsgi.application'
if os.environ.get('POSTGRES_HOST'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': os.environ['POSTGRES_HOST'],
        'NAME': os.environ.get('POSTGRES_DB', 'sersi'),
        'USER': os.environ.get('POSTGRES_USER', 'sersi'),
        'PASSWORD': os.environ['POSTGRES_PASSWORD'],
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }}
else:
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': RUNTIME_DIR / 'sersi.sqlite3',
        'OPTIONS': {'timeout': 30},
    }}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_ROOT = RUNTIME_DIR / 'documents'
MEDIA_URL = '/protected-media/'  # Never routed directly: downloads pass through a view.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000
SERSI_MAX_UPLOAD_BYTES = int(os.environ.get('SERSI_MAX_UPLOAD_BYTES', 50 * 1024 * 1024))
SERSI_EXPORT_MAX_BYTES = int(os.environ.get('SERSI_EXPORT_MAX_BYTES', 512 * 1024 * 1024))
SERSI_EXPORT_MAX_FILES = int(os.environ.get('SERSI_EXPORT_MAX_FILES', '2000'))
SERSI_BACKUP_DIR = Path(os.environ.get('SERSI_BACKUP_DIR', RUNTIME_DIR / 'backups'))
SERSI_BACKUP_UPLOAD_BYTES = int(os.environ.get('SERSI_BACKUP_UPLOAD_BYTES', 2 * 1024 ** 3))
SERSI_BACKUP_MAX_BYTES = int(os.environ.get('SERSI_BACKUP_MAX_BYTES', 10 * 1024 ** 3))
SERSI_BACKUP_MAX_FILES = 20000
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
TLS_ENABLED = os.environ.get('SERSI_HTTPS', '0') == '1'
SESSION_COOKIE_SECURE = TLS_ENABLED
CSRF_COOKIE_SECURE = TLS_ENABLED
SECURE_SSL_REDIRECT = TLS_ENABLED
SECURE_REDIRECT_EXEMPT = [r'^health/$']
if os.environ.get('SERSI_TRUST_PROXY', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000 if TLS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}, 'journal': {'class': 'catalogue.logging_handlers.JournalErrorHandler', 'level': 'ERROR'}},
    'loggers': {'django': {'handlers': ['console', 'journal'], 'level': 'INFO'}},
}

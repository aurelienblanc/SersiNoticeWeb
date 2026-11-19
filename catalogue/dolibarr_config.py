"""Validate Dolibarr endpoints and protect their server-side credentials."""
from base64 import urlsafe_b64encode
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.crypto import salted_hmac


LEGACY_SOURCE_NAME = 'Dolibarr historique'
MAX_KEY_LENGTH = 8192


def normalize_url(value):
    url = value.strip().rstrip('/').removesuffix('/api/index.php').rstrip('/')
    URLValidator(schemes=['https', 'http'])(url)
    parts = urlsplit(url)
    if parts.username is not None or parts.query or parts.fragment or '?' in url or '#' in url or '\\' in url:
        raise ValidationError('Saisissez l’adresse de Dolibarr sans identifiants ni paramètres.')
    try:
        parts.port
    except ValueError:
        raise ValidationError('Le port de l’adresse Dolibarr est invalide.') from None
    return parts._replace(netloc=parts.netloc.lower()).geturl()


def validate_connection_url(value):
    url = normalize_url(value)
    if not settings.DEBUG and not url.startswith('https://'):
        raise ValidationError('Utilisez une adresse HTTPS pour Dolibarr.')
    return url


def valid_api_key(key):
    return 0 < len(key) <= MAX_KEY_LENGTH and all(33 <= ord(char) <= 126 for char in key)


def _cipher(url):
    key = salted_hmac('sersi.dolibarr.api-key.v1', url, algorithm='sha256').digest()
    return Fernet(urlsafe_b64encode(key))


def encrypt_key(url, key):
    return _cipher(url).encrypt(key.encode('ascii')).decode('ascii')


def decrypt_key(url, token):
    if token:
        try:
            return _cipher(url).decrypt(token).decode('ascii')
        except (InvalidToken, UnicodeError):
            pass
    return ''


def legacy_connection():
    """Read the old server configuration once, when upgrading the database."""
    url = validate_connection_url(settings.SERSI_DOLIBARR_URL)
    key = settings.SERSI_DOLIBARR_API_KEY
    if not key and settings.SERSI_DOLIBARR_API_KEY_FILE:
        try:
            with Path(settings.SERSI_DOLIBARR_API_KEY_FILE).open(encoding='utf-8') as stream:
                key = stream.read(MAX_KEY_LENGTH + 1).strip()
        except (OSError, UnicodeError):
            key = ''
    return url, key if valid_api_key(key) else ''

"""Read-only Dolibarr retrieval and explicit matching to the local catalogue."""
import hashlib
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.exceptions import ValidationError
from django.db.models import TextChoices
from django.utils.html import strip_tags

from .dolibarr_config import decrypt_key, valid_api_key, validate_connection_url
from .models import ReferenceDolibarr

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_LINES = 500
TOTAL_TIMEOUT = 25


class DolibarrError(Exception):
    """A safe message that may be shown without leaking API responses or keys."""


class DolibarrRecordType(TextChoices):
    PROPOSAL = 'proposals', 'Proposition commerciale'
    ORDER = 'orders', 'Commande client'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def source_fingerprint(source):
    return hashlib.sha256(source.url.encode()).hexdigest()


def _object_id(value):
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) or (isinstance(value, str) and len(value) <= 19 and value.isdecimal()):
        number = int(value)
        return number if 0 < number < 2 ** 63 else 0
    return 0


class DolibarrClient:
    def __init__(self, source):
        try:
            url = validate_connection_url(source.url)
        except ValidationError:
            raise DolibarrError('L’adresse de connexion Dolibarr est invalide.') from None
        self.base_url = url + '/api/index.php'
        self.key = decrypt_key(url, source.cle_chiffree)
        if not valid_api_key(self.key):
            raise DolibarrError('La clé API Dolibarr doit être configurée par un administrateur.')
        self.opener = build_opener(NoRedirect())
        self.deadline = time.monotonic() + TOTAL_TIMEOUT

    def get_json(self, path):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DolibarrError('Dolibarr met trop de temps à répondre. Réessayez dans un instant.')
        request = Request(self.base_url + path, headers={
            'DOLAPIKEY': self.key, 'Accept': 'application/json', 'User-Agent': 'SERSI-Notices/1.0',
        }, method='GET')
        try:
            with self.opener.open(request, timeout=min(10, remaining)) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise DolibarrError('La réponse Dolibarr est trop volumineuse.')
            return json.loads(raw)
        except HTTPError as error:
            code = error.code
            error.close()
            if code in (401, 403):
                raise DolibarrError('Dolibarr refuse cet accès. Vérifiez la clé API et les droits de lecture du document et des produits.') from None
            if code == 404:
                raise DolibarrError('Le document ou un de ses produits est introuvable dans Dolibarr.') from None
            raise DolibarrError('Dolibarr ne peut pas répondre à cette demande. Vérifiez la connexion ou réessayez.') from None
        except (URLError, TimeoutError, OSError):
            raise DolibarrError('Impossible de joindre Dolibarr. Vérifiez la connexion ou réessayez.') from None
        except (ValueError, RecursionError, UnicodeError):
            raise DolibarrError('Dolibarr a renvoyé une réponse illisible.') from None

    def read_record(self, record_type, reference):
        endpoint = f'/{DolibarrRecordType(record_type).value}'
        record = self.get_json(f'{endpoint}/ref/{quote(reference, safe="")}')
        record_reference = record.get('ref') if isinstance(record, dict) else None
        if not isinstance(record_reference, str) or record_reference.casefold() != reference.casefold():
            raise DolibarrError('Dolibarr a renvoyé une référence différente ou invalide.')
        lines = record.get('lines')
        record_id = _object_id(record.get('id'))
        if lines is None and record_id:
            lines = self.get_json(f'{endpoint}/{record_id}/lines')
        if not isinstance(lines, list) or len(lines) > MAX_LINES or any(not isinstance(line, dict) for line in lines):
            raise DolibarrError('Les lignes du document Dolibarr sont invalides ou trop nombreuses.')
        products, entries = {}, []
        for number, line in enumerate(lines, 1):
            product_id = _object_id(line.get('fk_product', line.get('product_id')))
            label = strip_tags(str(line.get('label') or line.get('desc') or 'Ligne libre'))[:300]
            if not product_id:
                entries.append({'line': number, 'reference': '', 'label': label,
                                'reason': 'Ligne libre, sans produit Dolibarr associé.'})
                continue
            if product_id not in products:
                product = self.get_json(f'/products/{product_id}')
                if not isinstance(product, dict) or not isinstance(product.get('ref'), str) or not product['ref'].strip() or len(product['ref']) > 255:
                    raise DolibarrError('Dolibarr a renvoyé une référence produit invalide.')
                products[product_id] = product['ref'].strip()
            entries.append({'line': number, 'reference': products[product_id], 'label': label})
        return record_reference, entries


def matching_references(references):
    return ReferenceDolibarr.objects.filter(reference__in=references).select_related(
        'produit__marque',
    ).order_by('produit__reference', 'reference')


def group_matched_products(matches):
    products = {}
    for match in matches:
        item = products.setdefault(match.produit_id, {'product': match.produit, 'references': []})
        item['references'].append(match.reference)
    return list(products.values())


def match_record(source, record_type, reference):
    reference, entries = DolibarrClient(source).read_record(record_type, reference)
    references = {entry['reference'] for entry in entries if entry['reference']}
    matches = {}
    for match in matching_references(references):
        matches.setdefault(match.reference, []).append(match)
    selected, issues, matched_lines = {}, [], 0
    for entry in entries:
        candidates = matches.get(entry['reference'], [])
        if entry.get('reason'):
            issues.append(entry)
        elif not candidates:
            issues.append({**entry, 'reason': 'Aucune correspondance dans SERSI Notices.'})
        elif len(candidates) > 1:
            issues.append({**entry, 'reason': 'Plusieurs produits correspondent à cette référence : ' + ', '.join(match.produit.reference for match in candidates)})
        else:
            match = candidates[0]
            selected[(match.produit_id, match.reference)] = match
            matched_lines += 1
    return {'reference': reference, 'products': group_matched_products(selected.values()),
            'product_map': list(selected), 'issues': issues,
            'line_count': len(entries), 'matched_lines': matched_lines}

"""Portable, verified catalogue snapshots. Archives never contain credentials."""
import hashlib
import itertools
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management.color import no_style
from django.db import connection, transaction, models
from django.utils import timezone

from .admin_access import audit_principal
from .journal import record_event
from .models import (
    ActivityEvent, BackupRecord, Categorie, Document, DossierCible, ExportRecord,
    Marque, Produit, Systeme, TypeDocument, TypeExport, validate_folder_path,
)

CATALOGUE_MODELS = (Systeme, Categorie, Marque, TypeExport, TypeDocument, DossierCible, Document, Produit, ExportRecord)
MODELS = {model._meta.label_lower: model for model in CATALOGUE_MODELS}
METADATA = {'catalogue.json', 'historique.json', 'journal.json'}
JSON_LIMIT = 64 * 1024 * 1024
CHUNK = 1024 * 1024


class BackupError(Exception):
    pass


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup_directory():
    root = Path(settings.SERSI_BACKUP_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def backup_path(backup):
    if not re.fullmatch(r'sersi-[0-9a-f]{32}\.zip', backup.filename):
        raise BackupError('Le nom de la sauvegarde est invalide.')
    path = backup_directory() / backup.filename
    if path.is_symlink():
        raise BackupError('Les liens symboliques ne sont pas acceptés pour les sauvegardes.')
    return path


def safe_relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise BackupError('Une archive contient un chemin invalide.')
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
        raise BackupError('Une archive contient un chemin dangereux.')
    return path


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _snapshot():
    # All related rows are read from one database snapshot. Document uploads use
    # fresh UUIDs and never overwrite or delete an old file, so media stays stable.
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        rows = itertools.chain.from_iterable(model.objects.all().order_by('pk') for model in CATALOGUE_MODELS)
        catalogue = serializers.serialize('json', rows).encode('utf-8')
        history = [{
            'date': entry.action_time.isoformat(), 'modele': entry.content_type.model,
            'objet': entry.object_id, 'libelle': entry.object_repr,
            'action': entry.action_flag, 'modification': entry.change_message,
        } for entry in LogEntry.objects.filter(content_type__app_label='catalogue').select_related('content_type')]
        events = serializers.serialize('json', ActivityEvent.objects.all().order_by('created_at')).encode('utf-8')
    return catalogue, _json_bytes(history), events


def create_backup(origin='manual', progress=lambda percent, message: None):
    progress(2, 'Lecture du catalogue et des historiques…')
    catalogue, history, events = _snapshot()
    rows = json.loads(catalogue)
    names = sorted({row['fields']['fichier'] for row in rows if row['model'] == 'catalogue.document' and row['fields']['fichier']})
    if len(names) + 4 > settings.SERSI_BACKUP_MAX_FILES:
        raise BackupError('La sauvegarde dépasse le nombre maximal de fichiers.')
    identifier = uuid.uuid4()
    filename = f'sersi-{identifier.hex}.zip'
    temporary = backup_directory() / f'.{identifier.hex}.partial'
    destination = backup_directory() / filename
    manifest = {'format': 'sersi-notice-backup', 'version': 1, 'created_at': timezone.now().isoformat(),
                'products': sum(row['model'] == 'catalogue.produit' for row in rows),
                'documents': sum(row['model'] == 'catalogue.document' for row in rows),
                'files': len(names), 'entries': {}}
    media_root = Path(settings.MEDIA_ROOT).resolve()
    estimate = len(catalogue) + len(history) + len(events)
    for name in names:
        path = (media_root / str(safe_relative(name))).resolve()
        if not path.is_relative_to(media_root) or not path.is_file():
            raise BackupError('Un fichier référencé est introuvable. Rattachez-le avant de sauvegarder.')
        estimate += path.stat().st_size
    if estimate > settings.SERSI_BACKUP_MAX_BYTES:
        raise BackupError('La sauvegarde dépasse la taille maximale autorisée.')
    if shutil.disk_usage(backup_directory()).free < estimate + 128 * 1024 ** 2:
        raise BackupError('L’espace disponible est insuffisant pour créer une sauvegarde complète.')
    total = 0
    try:
        with zipfile.ZipFile(temporary, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name, data in [('catalogue.json', catalogue), ('historique.json', history), ('journal.json', events)]:
                if len(data) > JSON_LIMIT:
                    raise BackupError('Un historique est trop volumineux ; réduisez sa durée de conservation.')
                archive.writestr(name, data)
                manifest['entries'][name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                total += len(data)
            for index, name in enumerate(names):
                path = (media_root / str(safe_relative(name))).resolve()
                if not path.is_relative_to(media_root) or not path.is_file():
                    raise BackupError('Un fichier référencé est introuvable. Rattachez-le avant de sauvegarder.')
                member = f'documents/{name}'
                digest, size = hashlib.sha256(), 0
                with path.open('rb') as source, archive.open(member, 'w', force_zip64=True) as target:
                    while chunk := source.read(CHUNK):
                        size += len(chunk)
                        total += len(chunk)
                        if total > settings.SERSI_BACKUP_MAX_BYTES:
                            raise BackupError('La sauvegarde dépasse la taille maximale autorisée.')
                        digest.update(chunk)
                        target.write(chunk)
                manifest['entries'][member] = {'size': size, 'sha256': digest.hexdigest()}
                progress(5 + int((index + 1) * 65 / max(len(names), 1)), 'Copie des documents…')
            archive.writestr('manifest.json', _json_bytes(manifest))
        progress(72, 'Contrôle de l’intégrité de la sauvegarde…')
        validate_archive(temporary, lambda p, m: progress(72 + int(p * .25), m))
        digest = checksum(temporary)
        os.replace(temporary, destination)
        with transaction.atomic():
            backup = BackupRecord.objects.create(id=identifier, filename=filename, origin=origin,
                size=destination.stat().st_size, sha256=digest, products=manifest['products'],
                documents=manifest['documents'], files=manifest['files'], verified_at=timezone.now())
            record_event('backups', 'backup.created', 'Sauvegarde créée et vérifiée.', details={
                'sauvegarde': str(backup.pk), 'origine': origin, 'produits': backup.products,
                'documents': backup.documents, 'fichiers': backup.files,
            })
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return backup


def _validate_catalogue(rows, entries):
    if not isinstance(rows, list):
        raise BackupError('Le catalogue de la sauvegarde est invalide.')
    objects = {label: {} for label in MODELS}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'model', 'pk', 'fields'} or row['model'] not in MODELS:
            raise BackupError('La sauvegarde contient un type de données non autorisé.')
        label, pk, fields = row['model'], row['pk'], row['fields']
        if type(pk) is not int or pk < 1 or pk in objects[label] or not isinstance(fields, dict):
            raise BackupError('Les identifiants de la sauvegarde sont invalides.')
        expected = {field.name for field in (*MODELS[label]._meta.local_fields, *MODELS[label]._meta.local_many_to_many)
                    if field.serialize and not field.primary_key}
        if set(fields) != expected:
            raise BackupError('Cette sauvegarde ne correspond pas à la version du catalogue.')
        objects[label][pk] = fields
    for label, items in objects.items():
        model = MODELS[label]
        unique_values = {}
        for pk, fields in items.items():
            for name, value in fields.items():
                field = model._meta.get_field(name)
                if field.is_relation:
                    values = value if field.many_to_many else ([] if value is None and field.null else [value])
                    if not isinstance(values, list) or any(type(v) is not int or v not in objects[field.related_model._meta.label_lower] for v in values):
                        raise BackupError('La sauvegarde contient des relations documentaires invalides.')
                    if field.many_to_many and len(set(values)) != len(values):
                        raise BackupError('La sauvegarde contient des relations en double.')
                else:
                    try:
                        converted = field.to_python(value)
                        field.validate(converted, model())
                        if not isinstance(field, models.FileField):
                            field.run_validators(converted)
                    except Exception as error:
                        raise BackupError('Une valeur du catalogue sauvegardé est invalide.') from error
                    if field.unique:
                        previous = unique_values.setdefault(name, set())
                        if value in previous:
                            raise BackupError('La sauvegarde contient une référence en double.')
                        previous.add(value)
            if model is DossierCible:
                try:
                    validate_folder_path(fields['chemin_relatif'])
                except Exception as error:
                    raise BackupError('Un dossier cible sauvegardé est invalide.') from error
                seen, parent = {pk}, fields['parent']
                while parent:
                    if parent in seen:
                        raise BackupError('La sauvegarde contient une boucle de dossiers.')
                    seen.add(parent)
                    parent = items[parent]['parent']
    referenced = {f'documents/{safe_relative(fields["fichier"])}'
                  for fields in objects['catalogue.document'].values() if fields['fichier']}
    if referenced != set(entries) - METADATA:
        raise BackupError('Les fichiers de la sauvegarde ne correspondent pas au catalogue.')
    return objects


def validate_archive(path, progress=lambda percent, message: None):
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or len(names) > settings.SERSI_BACKUP_MAX_FILES:
                raise BackupError('L’archive contient trop de fichiers ou des entrées en double.')
            if sum(info.file_size for info in infos) > settings.SERSI_BACKUP_MAX_BYTES:
                raise BackupError('L’archive décompressée est trop volumineuse.')
            for info in infos:
                safe_relative(info.filename)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise BackupError('Les répertoires, liens et archives chiffrées ne sont pas acceptés.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > JSON_LIMIT:
                raise BackupError('Le manifeste de sauvegarde est absent ou invalide.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'sersi-notice-backup' or manifest.get('version') != 1:
                raise BackupError('Ce fichier n’est pas une sauvegarde SERSI Notice compatible.')
            entries = manifest.get('entries')
            if not isinstance(entries, dict) or set(entries) | {'manifest.json'} != set(names) or not METADATA.issubset(entries):
                raise BackupError('Le contenu ne correspond pas au manifeste de sauvegarde.')
            for index, (name, expected) in enumerate(entries.items()):
                info = archive.getinfo(name)
                if not isinstance(expected, dict) or expected.get('size') != info.file_size:
                    raise BackupError('La taille d’un fichier ne correspond pas au manifeste.')
                if name in METADATA and info.file_size > JSON_LIMIT:
                    raise BackupError('Les métadonnées de la sauvegarde sont trop volumineuses.')
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                if digest.hexdigest() != expected.get('sha256'):
                    raise BackupError('Le contrôle d’intégrité de la sauvegarde a échoué.')
                progress(int((index + 1) * 100 / len(entries)), 'Vérification des fichiers…')
            rows = json.loads(archive.read('catalogue.json'))
            objects = _validate_catalogue(rows, entries)
            history = json.loads(archive.read('historique.json'))
            if not isinstance(history, list) or any(not isinstance(item, dict) or item.get('modele') not in {m._meta.model_name for m in CATALOGUE_MODELS}
                or item.get('action') not in (1, 2, 3) or set(item) != {'date', 'modele', 'objet', 'libelle', 'action', 'modification'} for item in history):
                raise BackupError('L’historique de la sauvegarde est invalide.')
            events = json.loads(archive.read('journal.json'))
            if not isinstance(events, list) or any(not isinstance(item, dict) or item.get('model') != 'catalogue.activityevent' for item in events):
                raise BackupError('Le journal de la sauvegarde est invalide.')
            # Deserialization validates UUIDs, dates and field types, without saving.
            for item in serializers.deserialize('json', json.dumps(events)):
                item.object.full_clean(validate_unique=False, validate_constraints=False)
            if manifest.get('products') != len(objects['catalogue.produit']) or manifest.get('documents') != len(objects['catalogue.document']) or manifest.get('files') != len(entries) - len(METADATA):
                raise BackupError('Les compteurs du manifeste sont invalides.')
            return manifest
    except BackupError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ValidationError, zipfile.BadZipFile, serializers.base.DeserializationError) as error:
        raise BackupError('La sauvegarde est illisible ou endommagée.') from error


def verify_backup(backup, progress=lambda percent, message: None):
    path = backup_path(backup)
    if checksum(path) != backup.sha256:
        raise BackupError('Le fichier de sauvegarde a changé depuis son enregistrement.')
    manifest = validate_archive(path, progress)
    backup.verified_at = timezone.now()
    backup.products, backup.documents, backup.files = manifest['products'], manifest['documents'], manifest['files']
    backup.save(update_fields=['verified_at', 'products', 'documents', 'files'])
    return manifest


def restore_backup(backup, progress=lambda percent, message: None):
    path = backup_path(backup)
    progress(1, 'Vérification de la sauvegarde à restaurer…')
    verify_backup(backup, lambda p, m: progress(1 + int(p * .14), m))
    progress(16, 'Création d’une sauvegarde de protection…')
    safety = create_backup('safety', lambda p, m: progress(16 + int(p * .39), m))
    copied = []
    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as archive:
            size = sum(info.file_size for info in archive.infolist() if info.filename.startswith('documents/'))
            if shutil.disk_usage(media_root).free < size + 128 * 1024 ** 2:
                raise BackupError('L’espace disponible est insuffisant pour préparer les documents restaurés.')
            rows = json.loads(archive.read('catalogue.json'))
            replacements = {}
            for row in rows:
                if row['model'] != 'catalogue.document' or not row['fields']['fichier']:
                    continue
                previous = row['fields']['fichier']
                if previous not in replacements:
                    suffix = PurePosixPath(previous).suffix[:12]
                    name = f'{uuid.uuid4().hex}{suffix}'
                    destination = media_root / name
                    with archive.open(f'documents/{previous}') as source, destination.open('xb') as target:
                        copied.append(destination)
                        shutil.copyfileobj(source, target, CHUNK)
                    replacements[previous] = name
                row['fields']['fichier'] = replacements[previous]
                progress(57 + int(len(replacements) * 25 / max(backup.files, 1)), 'Préparation des documents restaurés…')
            history = json.loads(archive.read('historique.json'))
            events = archive.read('journal.json').decode('utf-8')
        progress(85, 'Restauration du catalogue…')
        with transaction.atomic():
            # Lock business tables before deleting anything; settings, credential,
            # sessions, backup records and job state are intentionally untouched.
            if connection.vendor == 'postgresql':
                tables = [model._meta.db_table for model in CATALOGUE_MODELS]
                tables += [Produit.systemes.through._meta.db_table, Produit.documents.through._meta.db_table, Document.dossiers.through._meta.db_table]
                with connection.cursor() as cursor:
                    cursor.execute('LOCK TABLE ' + ', '.join(connection.ops.quote_name(t) for t in tables) + ' IN ACCESS EXCLUSIVE MODE')
            Produit.objects.all().delete()
            Document.objects.all().delete()
            DossierCible.objects.update(parent=None)
            DossierCible.objects.all().delete()
            for model in (TypeDocument, TypeExport, Systeme, Categorie, Marque, ExportRecord):
                model.objects.all().delete()
            for obj in serializers.deserialize('json', json.dumps(rows)):
                obj.save()
            connection.check_constraints()
            with connection.cursor() as cursor:
                for sql in connection.ops.sequence_reset_sql(no_style(), CATALOGUE_MODELS):
                    cursor.execute(sql)
            LogEntry.objects.filter(content_type__app_label='catalogue').delete()
            principal = audit_principal()
            content_types = {model._meta.model_name: ContentType.objects.get_for_model(model) for model in CATALOGUE_MODELS}
            LogEntry.objects.bulk_create([LogEntry(
                user=principal, content_type=content_types[item['modele']], action_time=item['date'],
                object_id=item['objet'], object_repr=item['libelle'], action_flag=item['action'], change_message=item['modification'],
            ) for item in history])
            # Preserve current maintenance/security events as well as the archive's
            # older history, deduplicated by immutable UUID.
            ActivityEvent.objects.bulk_create([obj.object for obj in serializers.deserialize('json', events)], ignore_conflicts=True)
            record_event('backups', 'backup.restored', 'Catalogue et documents restaurés.', details={
                'sauvegarde': str(backup.pk), 'protection': str(safety.pk), 'produits': backup.products,
                'documents': backup.documents,
            })
    except Exception:
        for file in copied:
            file.unlink(missing_ok=True)
        raise
    return safety

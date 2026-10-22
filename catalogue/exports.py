import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Document, validate_folder_path


def safe_segment(value):
    value = unicodedata.normalize('NFC', str(value))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:150]
    if not value:
        return 'Sans nom'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        value = '_' + value
    return value


def archive_filename(selection):
    parts = [selection.get(key, '').strip() for key in ('client', 'projet')]
    name = ' - '.join(part for part in parts if part) or 'Dossier documentaire'
    return f'{safe_segment(name)}.zip'


def folder_path(folder):
    seen, chunks = set(), []
    while folder:
        if folder.pk in seen:
            raise ValidationError('Boucle dans les dossiers cibles.')
        seen.add(folder.pk)
        validate_folder_path(folder.chemin_relatif)
        chunks.insert(0, [safe_segment(part) for part in re.split(r'[/\\]', folder.chemin_relatif) if part])
        folder = folder.parent
    return '/'.join(part for chunk in chunks for part in chunk)


@dataclass
class PlannedFile:
    document: Document
    chemin: str
    taille: int


@dataclass
class Issue:
    nom: str
    raison: str


@dataclass
class ExportPlan:
    fichiers: list = field(default_factory=list)
    indisponibles: list = field(default_factory=list)
    expires: list = field(default_factory=list)
    taille: int = 0

    @property
    def contient_expires(self):
        return any(item.document.expire for item in self.fichiers)


def build_plan(products, export_types, include_expired=True):
    plan = ExportPlan()
    selected_ids = set(export_types.values_list('pk', flat=True))
    labels = set(export_types.values_list('libelle', flat=True))
    used = set()
    documents = Document.objects.filter(produits__in=products).distinct().select_related('type_document').prefetch_related('dossiers__parent')
    for document in documents:
        kind = document.type_document
        if kind.type_export_id:
            eligible = kind.type_export_id in selected_ids
        else:
            eligible = ('commercial' in labels and kind.nom == 'Fiche commercial') or ('techniques' in labels and kind.nom != 'Fiche commercial')
        if not eligible:
            continue
        if document.expire and not include_expired:
            plan.expires.append(document)
            continue
        if not document.disponible:
            plan.indisponibles.append(Issue(document.nom, 'Fichier à déposer sur le serveur'))
            continue
        folders = list(document.dossiers.all())
        if not folders:
            plan.indisponibles.append(Issue(document.nom, 'Aucun dossier cible configuré'))
            continue
        size = Path(document.fichier.path).stat().st_size
        filename = safe_segment(document.nom_fichier or document.nom + Path(document.fichier.name).suffix)
        for folder in folders:
            try:
                directory = folder_path(folder)
            except ValidationError:
                plan.indisponibles.append(Issue(document.nom, 'Hiérarchie de dossiers invalide'))
                continue
            original = f'{directory}/{filename}'
            arcname, counter = original, 2
            while arcname.casefold() in used:
                stem, suffix = Path(filename).stem, Path(filename).suffix
                arcname = f'{directory}/{stem}_{counter}{suffix}'
                counter += 1
            used.add(arcname.casefold())
            plan.taille += size
            plan.fichiers.append(PlannedFile(document, arcname, size))
            if len(plan.fichiers) > settings.SERSI_EXPORT_MAX_FILES or plan.taille > settings.SERSI_EXPORT_MAX_BYTES:
                raise ValidationError('Sélection trop volumineuse. Réduisez le nombre de produits.')
    return plan


def create_archive(plan, selection):
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    try:
        total = 0
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            for item in plan.fichiers:
                if not item.document.disponible:
                    raise ValidationError('Un fichier a changé depuis la préparation. Préparez à nouveau le dossier.')
                total += Path(item.document.fichier.path).stat().st_size
                if total > settings.SERSI_EXPORT_MAX_BYTES:
                    raise ValidationError('Le dossier dépasse la taille maximale autorisée.')
                archive.write(item.document.fichier.path, item.chemin)
        output.seek(0)
        return output, archive_filename(selection)
    except Exception:
        output.close()
        raise

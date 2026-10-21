"""One-time, read-only import from the Qt application's SQLite database."""
import csv
import re
import sqlite3
from pathlib import Path, PureWindowsPath

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from catalogue.models import Categorie, Document, DossierCible, Marque, Produit, Systeme, TypeDocument, TypeExport

CATALOGUE_MODELS = [Systeme, Categorie, Marque, TypeExport, TypeDocument, DossierCible, Document, Produit]


class FileResolver:
    def __init__(self, root, mappings):
        self.root = Path(root).resolve() if root else None
        self.mappings = []
        self.names = {}
        for mapping in mappings:
            old, sep, new = mapping.partition('=')
            if not sep or not old or not new:
                raise CommandError('Format attendu pour --path-map : ANCIEN=NOUVEAU')
            self.mappings.append((old.replace('\\', '/').rstrip('/'), Path(new)))
        if self.root:
            if not self.root.is_dir():
                raise CommandError('Le répertoire documentaire est introuvable.')
            for file in self.root.rglob('*'):
                if file.is_file() and file.resolve().is_relative_to(self.root):
                    self.names.setdefault(file.name.casefold(), []).append(file)

    def resolve(self, old_path):
        if not self.root or not old_path:
            return None, 'Fichier à déposer'
        normalized = old_path.replace('\\', '/')
        candidates = []
        for old, new in self.mappings:
            if normalized.casefold().startswith(old.casefold() + '/'):
                candidates.append(new / normalized[len(old) + 1:])
        candidates.append(Path(old_path))
        candidates.append(self.root / normalized)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_relative_to(self.root) and resolved.is_file():
                return resolved, 'Copié'
        matches = self.names.get(PureWindowsPath(old_path).name.casefold(), [])
        if len(matches) == 1:
            return matches[0], 'Copié (nom unique)'
        return None, 'Plusieurs fichiers de même nom' if matches else 'Fichier introuvable'


class Command(BaseCommand):
    help = 'Importe une base SERSI Notice bureau dans un catalogue web vide, sans modifier la source.'

    def add_arguments(self, parser):
        parser.add_argument('database', type=Path)
        parser.add_argument('--documents-root', type=Path)
        parser.add_argument('--path-map', action='append', default=[])
        parser.add_argument('--dry-run', action='store_true', help='Valider sans conserver de données ni copier de fichiers.')
        parser.add_argument('--report', type=Path)

    def handle(self, *args, **options):
        source = options['database'].resolve()
        if not source.is_file():
            raise CommandError('La base source est introuvable.')
        if any(model.objects.exists() for model in CATALOGUE_MODELS):
            raise CommandError('Import refusé : le catalogue web doit être vide. Aucune donnée existante n’a été modifiée.')
        resolver = FileResolver(options['documents_root'], options['path_map'])
        copied, report = [], []
        legacy = None
        try:
            legacy = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
            legacy.row_factory = sqlite3.Row
            with transaction.atomic():
                self.import_rows(legacy, resolver, options['dry_run'], copied, report)
                # Preserve imported IDs and reset PostgreSQL identity sequences.
                for sql in connection.ops.sequence_reset_sql(no_style(), CATALOGUE_MODELS):
                    with connection.cursor() as cursor:
                        cursor.execute(sql)
                counts = ', '.join(f'{model._meta.verbose_name_plural}: {model.objects.count()}' for model in [Produit, Document, Systeme, Marque])
                report_path = options['report'] or settings.RUNTIME_DIR / 'rapport-import.csv'
                report_path.parent.mkdir(parents=True, exist_ok=True)
                with report_path.open('w', encoding='utf-8-sig', newline='') as output:
                    writer = csv.writer(output, delimiter=';')
                    writer.writerow(['id', 'document', 'ancien_chemin', 'état'])
                    writer.writerows(report)
                if options['dry_run']:
                    transaction.set_rollback(True)
        except Exception as error:
            # Only remove files created by this failed import.
            for field in copied:
                field.storage.delete(field.name)
            if isinstance(error, CommandError):
                raise
            raise CommandError(f'Import annulé : {error}') from error
        finally:
            if legacy:
                legacy.close()
        unavailable = sum(1 for row in report if not row[3].startswith('Copié'))
        prefix = 'Simulation terminée' if options['dry_run'] else 'Import terminé'
        self.stdout.write(self.style.SUCCESS(f'{prefix} — {counts}.'))
        self.stdout.write(f'{unavailable} fichier(s) à vérifier. Rapport : {report_path}')

    def import_rows(self, db, resolver, dry_run, copied, report):
        def rows(table):
            return [dict(row) for row in db.execute(f'SELECT * FROM [{table}]')]

        for model, table in [(Systeme, 'Systeme'), (Categorie, 'Categorie'), (Marque, 'Marque'), (TypeExport, 'TypeExport')]:
            for row in rows(table):
                values = {key: row[key] for key in ('nom', 'libelle', 'ordre', 'generique') if key in row}
                if 'ordre' in values:
                    values['ordre'] = values['ordre'] or 0
                model.objects.create(pk=row['id'], **values)
        for row in rows('TypeDocument'):
            TypeDocument.objects.create(pk=row['id'], nom=row['nom'], type_export_id=row.get('id_type_export'))
        folders = rows('DossierCible')
        for row in folders:
            DossierCible.objects.create(pk=row['id'], nom=row['nom'], chemin_relatif=row['chemin_relatif'], ordre=row.get('ordre') or 0)
        for row in folders:
            if row.get('parent_id'):
                folder = DossierCible.objects.get(pk=row['id'])
                folder.parent_id = row['parent_id']
                folder.full_clean()
                folder.save()
        for folder in DossierCible.objects.all():
            folder.full_clean()
        for row in rows('Produit'):
            Produit.objects.create(pk=row['id'], reference=row['reference'], nom=row['nom'],
                                   description=row.get('description') or '', actif=bool(row.get('actif', True)),
                                   marque_id=row['id_marque'], categorie_id=row['id_categorie'])
        for row in rows('Document'):
            old = row['chemin_relatif'] or ''
            doc = Document(pk=row['id'], nom=row['nom'], type_document_id=row['id_type_document'],
                           ancien_chemin=old, nom_fichier=PureWindowsPath(old).name,
                           chemin_sharepoint=row.get('chemin_sharepoint') or '',
                           date_expiration=row.get('date_expiration') or None, indice=row.get('indice') or '')
            path, status = resolver.resolve(old)
            if path and not dry_run:
                with path.open('rb') as content:
                    doc.fichier.save(path.name, File(content), save=False)
                copied.append(doc.fichier)
            doc.save()
            report.append([doc.pk, doc.nom, old, status])
        for row in rows('Produit_Systeme'):
            Produit.objects.get(pk=row['id_produit']).systemes.add(row['id_systeme'])
        for row in rows('Produit_Document'):
            Produit.objects.get(pk=row['id_produit']).documents.add(row['id_document'])
        for row in rows('Document_Dossier'):
            Document.objects.get(pk=row['id_document']).dossiers.add(row['id_dossier'])

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from catalogue.management.commands.import_legacy import FileResolver
from catalogue.models import Document


class Command(BaseCommand):
    help = 'Rattache les fichiers manquants après un import des métadonnées.'

    def add_arguments(self, parser):
        parser.add_argument('documents_root', type=Path)
        parser.add_argument('--path-map', action='append', default=[])
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        resolver = FileResolver(options['documents_root'], options['path_map'])
        attached = missing = 0
        for doc in Document.objects.exclude(ancien_chemin=''):
            if doc.disponible:
                continue
            path, _ = resolver.resolve(doc.ancien_chemin)
            if not path:
                missing += 1
                continue
            if not options['dry_run']:
                with path.open('rb') as content:
                    doc.fichier.save(path.name, File(content), save=False)
                try:
                    doc.save()
                except Exception:
                    doc.fichier.storage.delete(doc.fichier.name)
                    raise
            attached += 1
        self.stdout.write(f'{attached} fichier(s) rattachable(s), {missing} introuvable(s).' if options['dry_run'] else f'{attached} fichier(s) rattaché(s), {missing} introuvable(s).')

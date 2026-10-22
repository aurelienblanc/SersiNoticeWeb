import shutil
import sys

from django.core.management.base import BaseCommand, CommandError

from catalogue.backups import backup_path, create_backup
from catalogue.maintenance import maintenance_lock


class Command(BaseCommand):
    help = 'Crée une sauvegarde portable du catalogue, des documents et des historiques.'

    def add_arguments(self, parser):
        parser.add_argument('--stdout', dest='archive_stdout', action='store_true', help='Envoyer l’archive ZIP sur la sortie standard.')

    def handle(self, *args, **options):
        with maintenance_lock() as acquired:
            if not acquired:
                raise CommandError('Une opération de maintenance est déjà en cours.')
            backup = create_backup()
        path = backup_path(backup)
        if options['archive_stdout']:
            with path.open('rb') as stream:
                shutil.copyfileobj(stream, sys.stdout.buffer)
        else:
            self.stdout.write(str(path))

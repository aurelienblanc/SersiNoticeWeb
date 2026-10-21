import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from catalogue.maintenance import housekeeping, run_pending_job
from catalogue.models import MaintenanceSettings


class Command(BaseCommand):
    help = 'Exécute les sauvegardes planifiées, les vérifications et les restaurations.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--check-health', action='store_true')

    def handle(self, *args, **options):
        if options['check_health']:
            config = MaintenanceSettings.objects.filter(pk=1).first()
            if not config or not config.worker_seen_at or (timezone.now() - config.worker_seen_at).total_seconds() > 90:
                raise CommandError('Le service de maintenance ne répond pas.')
            return
        while True:
            close_old_connections()
            housekeeping()
            job = run_pending_job()
            if job:
                self.stdout.write(f'{job.get_kind_display()} : {job.get_status_display()}.')
            if options['once']:
                return
            time.sleep(5)

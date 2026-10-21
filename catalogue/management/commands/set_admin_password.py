import getpass
import sys

from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from catalogue.models import AdministrationAccess, AdministrationAttempt


class Command(BaseCommand):
    help = 'Définit ou réinitialise le mot de passe commun de l’administration.'

    def add_arguments(self, parser):
        parser.add_argument('--password-stdin', action='store_true', help='Lire le mot de passe sur l’entrée standard.')

    def handle(self, *args, **options):
        if options['password_stdin']:
            password = sys.stdin.readline().rstrip('\r\n')
        else:
            password = getpass.getpass('Nouveau mot de passe commun : ')
            if password != getpass.getpass('Confirmation : '):
                raise CommandError('Les mots de passe sont différents.')
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError(' '.join(error.messages)) from error
        AdministrationAccess.objects.update_or_create(pk=1, defaults={'password_hash': make_password(password)})
        AdministrationAttempt.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('Mot de passe commun enregistré. Les sessions précédentes sont invalidées.'))

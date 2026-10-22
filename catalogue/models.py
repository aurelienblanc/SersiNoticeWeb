import re
import uuid
from datetime import time
from pathlib import Path, PureWindowsPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class NomModel(models.Model):
    nom = models.CharField('nom', max_length=255, unique=True)

    class Meta:
        abstract = True
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Systeme(NomModel):
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'système'


class Marque(NomModel):
    generique = models.BooleanField('marque générique', default=False, help_text='Proposée avec toutes les marques.')


class Categorie(NomModel):
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'catégorie'


class TypeExport(models.Model):
    libelle = models.CharField('libellé', max_length=255, unique=True)
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'libelle']
        verbose_name = "type d’export"

    def __str__(self):
        return self.libelle


class TypeDocument(NomModel):
    # Nullable for legacy imports/backups; new admin entries require a group.
    type_export = models.ForeignKey(TypeExport, on_delete=models.PROTECT, null=True, verbose_name="type d’export")

    class Meta(NomModel.Meta):
        abstract = False
        verbose_name = 'type de document'


def validate_folder_path(value):
    parts = re.split(r'[/\\]', value)
    if PureWindowsPath(value).is_absolute() or value.startswith(('/', '\\')) or any(p in ('..', '.') for p in parts):
        raise ValidationError('Utilisez un chemin relatif sans « . » ni « .. ».')
    if any(re.search(r'[<>:"|?*\x00-\x1f]', part) for part in parts):
        raise ValidationError('Le chemin contient des caractères interdits.')


class DossierCible(models.Model):
    nom = models.CharField('nom', max_length=255)
    chemin_relatif = models.CharField('chemin relatif', max_length=500, validators=[validate_folder_path])
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='enfants')
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'dossier cible'

    def __str__(self):
        return self.nom

    def clean(self):
        super().clean()
        seen = {self.pk} if self.pk else set()
        current = self.parent
        while current:
            if current.pk in seen:
                raise ValidationError({'parent': 'La hiérarchie de dossiers contient une boucle.'})
            seen.add(current.pk)
            current = current.parent


def document_path(instance, filename):
    instance.nom_fichier = Path(filename).name
    suffix = Path(filename).suffix[:12]
    return f'{uuid.uuid4().hex}{suffix}'


def validate_upload(file):
    if file.size > settings.SERSI_MAX_UPLOAD_BYTES:
        raise ValidationError(f'Fichier trop volumineux (maximum {settings.SERSI_MAX_UPLOAD_BYTES // 1024 // 1024} Mo).')


class Document(models.Model):
    nom = models.CharField('nom', max_length=500)
    type_document = models.ForeignKey(TypeDocument, on_delete=models.PROTECT, verbose_name='type de document')
    fichier = models.FileField('fichier sur le serveur', upload_to=document_path, blank=True, validators=[validate_upload])
    nom_fichier = models.CharField('nom du fichier original', max_length=500, blank=True)
    ancien_chemin = models.TextField('ancien chemin (migration)', blank=True)
    chemin_sharepoint = models.URLField('lien SharePoint', max_length=2000, blank=True)
    date_expiration = models.DateField("date d’expiration", null=True, blank=True)
    indice = models.CharField('indice', max_length=100, blank=True)
    dossiers = models.ManyToManyField(DossierCible, verbose_name='dossiers cibles', blank=True)

    class Meta:
        ordering = ['nom', 'id']

    def __str__(self):
        return self.nom

    @property
    def expire(self):
        return bool(self.date_expiration and self.date_expiration < timezone.localdate())

    @property
    def disponible(self):
        if not self.fichier:
            return False
        try:
            path = Path(self.fichier.path).resolve()
            return path.is_relative_to(Path(settings.MEDIA_ROOT).resolve()) and path.is_file()
        except (ValueError, OSError):
            return False

    def save(self, *args, **kwargs):
        if self.fichier and not self.fichier._committed:
            self.nom_fichier = Path(self.fichier.name).name
        super().save(*args, **kwargs)


class Produit(models.Model):
    reference = models.CharField('référence', max_length=255, unique=True)
    nom = models.CharField('nom', max_length=500)
    description = models.TextField(blank=True)
    marque = models.ForeignKey(Marque, on_delete=models.PROTECT)
    categorie = models.ForeignKey(Categorie, on_delete=models.PROTECT, verbose_name='catégorie')
    actif = models.BooleanField('actif', default=True)
    systemes = models.ManyToManyField(Systeme, verbose_name='systèmes', related_name='produits')
    documents = models.ManyToManyField(Document, related_name='produits', blank=True)

    class Meta:
        ordering = ['categorie__ordre', 'categorie__nom', 'nom', 'reference']

    def __str__(self):
        return f'{self.reference} · {self.nom}'


class ExportRecord(models.Model):
    created_at = models.DateTimeField('date', auto_now_add=True)
    projet = models.CharField('projet', max_length=200, blank=True)
    nombre_produits = models.PositiveIntegerField('produits')
    nombre_fichiers = models.PositiveIntegerField('fichiers')
    incomplet = models.BooleanField('export incomplet', default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'export'


class AdministrationAccess(models.Model):
    """One shared credential, separate from Django's account passwords."""
    password_hash = models.CharField(max_length=255)


class AdministrationAttempt(models.Model):
    """A short-lived login limit shared by all server workers."""
    key = models.CharField(max_length=64, primary_key=True)
    failures = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField()
    blocked_until = models.DateTimeField(null=True)


class ActivityEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    level = models.CharField(max_length=10, default='INFO', choices=[('INFO', 'Information'), ('WARNING', 'Attention'), ('ERROR', 'Erreur')])
    category = models.CharField(max_length=20, db_index=True, choices=[('catalogue', 'Catalogue'), ('exports', 'Exports'), ('security', 'Accès administration'), ('backups', 'Sauvegardes'), ('system', 'Technique')])
    event = models.CharField(max_length=80)
    message = models.CharField(max_length=1000)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class MaintenanceSettings(models.Model):
    automatic_backups = models.BooleanField(default=True)
    backup_time = models.TimeField(default=time(2, 0))
    automatic_retention = models.PositiveIntegerField(default=7)
    log_retention_days = models.PositiveIntegerField(default=90)
    last_scheduled_date = models.DateField(default=timezone.localdate)
    last_cleanup_date = models.DateField(null=True)
    worker_seen_at = models.DateTimeField(null=True)


class BackupRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    origin = models.CharField(max_length=12, choices=[('manual', 'Manuelle'), ('automatic', 'Automatique'), ('safety', 'Protection avant restauration'), ('upload', 'Archive importée')])
    filename = models.CharField(max_length=80, unique=True)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    products = models.PositiveIntegerField(default=0)
    documents = models.PositiveIntegerField(default=0)
    files = models.PositiveIntegerField(default=0)
    verified_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-created_at']


class MaintenanceJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    kind = models.CharField(max_length=10, choices=[('backup', 'Sauvegarde'), ('verify', 'Vérification'), ('restore', 'Restauration')])
    origin = models.CharField(max_length=12, default='manual')
    status = models.CharField(max_length=10, default='queued', choices=[('queued', 'En attente'), ('running', 'En cours'), ('done', 'Terminée'), ('failed', 'Échec')])
    progress = models.PositiveSmallIntegerField(default=0)
    message = models.CharField(max_length=1000, blank=True)
    backup = models.ForeignKey(BackupRecord, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']

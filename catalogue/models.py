import re
import uuid
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
    type_export = models.ForeignKey(TypeExport, on_delete=models.PROTECT, null=True, blank=True, verbose_name="type d’export")

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

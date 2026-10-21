from django import forms
from django.contrib import admin
from django.db import models
from django.urls import reverse
from django.utils.html import format_html

from .models import Categorie, Document, DossierCible, ExportRecord, Marque, Produit, Systeme, TypeDocument, TypeExport


@admin.register(Systeme, Categorie)
class OrderedAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ordre']
    list_editable = ['ordre']
    search_fields = ['nom']


@admin.register(Marque)
class MarqueAdmin(admin.ModelAdmin):
    list_display = ['nom', 'generique']
    list_filter = ['generique']
    search_fields = ['nom']


@admin.register(TypeExport)
class TypeExportAdmin(admin.ModelAdmin):
    list_display = ['libelle', 'ordre']
    search_fields = ['libelle']


@admin.register(TypeDocument)
class TypeDocumentAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_export']
    list_filter = ['type_export']
    search_fields = ['nom']


@admin.register(DossierCible)
class FolderAdmin(admin.ModelAdmin):
    list_display = ['nom', 'chemin_relatif', 'parent', 'ordre']
    search_fields = ['nom', 'chemin_relatif']


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_document', 'indice', 'date_expiration', 'etat_fichier']
    list_filter = ['type_document__type_export', 'type_document', 'date_expiration']
    search_fields = ['nom', 'nom_fichier', 'indice', 'ancien_chemin']
    filter_horizontal = ['dossiers']
    readonly_fields = ['nom_fichier', 'ancien_chemin', 'etat_fichier', 'telechargement']
    formfield_overrides = {models.FileField: {'widget': forms.FileInput}}
    list_select_related = ['type_document']

    @admin.display(description='État du fichier')
    def etat_fichier(self, obj):
        if not obj.disponible:
            return 'À déposer'
        if obj.expire:
            return 'Expiré'
        return 'Disponible'

    @admin.display(description='Téléchargement')
    def telechargement(self, obj):
        if not obj.pk or not obj.disponible:
            return 'Aucun fichier disponible'
        return format_html('<a href="{}">{}</a>', reverse('download_document', args=[obj.pk]), obj.nom_fichier or obj.nom)


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ['reference', 'nom', 'marque', 'categorie', 'actif']
    list_filter = ['actif', 'systemes', 'marque', 'categorie']
    search_fields = ['reference', 'nom', 'description']
    filter_horizontal = ['systemes', 'documents']
    list_select_related = ['marque', 'categorie']


@admin.register(ExportRecord)
class ExportAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'projet', 'nombre_produits', 'nombre_fichiers', 'incomplet']
    list_filter = ['incomplet', 'created_at']
    readonly_fields = ['created_at', 'projet', 'nombre_produits', 'nombre_fichiers', 'incomplet']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

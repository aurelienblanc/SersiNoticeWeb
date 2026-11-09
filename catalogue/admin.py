from django import forms
from django.contrib import admin
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from .dolibarr_config import decrypt_key
from .dolibarr_forms import DolibarrSourceForm
from .models import (
    Categorie, Document, DolibarrSource, DossierCible,
    ExportRecord, Marque, Produit, ReferenceDolibarr, Systeme, TypeDocument, TypeExport,
)
from .admin_site import admin_site


@admin.register(Systeme, Categorie, site=admin_site)
class OrderedAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ordre']
    list_editable = ['ordre']
    search_fields = ['nom']


@admin.register(Marque, site=admin_site)
class MarqueAdmin(admin.ModelAdmin):
    list_display = ['nom', 'generique']
    list_filter = ['generique']
    search_fields = ['nom']


@admin.register(TypeExport, site=admin_site)
class TypeExportAdmin(admin.ModelAdmin):
    list_display = ['libelle', 'ordre']
    search_fields = ['libelle']


@admin.register(TypeDocument, site=admin_site)
class TypeDocumentAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_export']
    list_filter = ['type_export']
    search_fields = ['nom']


@admin.register(DossierCible, site=admin_site)
class FolderAdmin(admin.ModelAdmin):
    list_display = ['nom', 'chemin_relatif', 'parent', 'ordre']
    search_fields = ['nom', 'chemin_relatif']


@admin.register(Document, site=admin_site)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_document', 'indice', 'date_expiration', 'etat_fichier']
    list_filter = ['type_document__type_export', 'type_document', 'date_expiration']
    search_fields = ['nom', 'nom_fichier', 'indice']
    filter_horizontal = ['dossiers']
    readonly_fields = ['nom_fichier', 'etat_fichier', 'telechargement']
    formfield_overrides = {models.FileField: {'widget': forms.FileInput}}
    list_select_related = ['type_document']
    fieldsets = [
        ('Document', {'fields': ['nom', 'type_document', 'indice', 'date_expiration']}),
        ('Fichier et classement', {'fields': ['fichier', 'etat_fichier', 'telechargement', 'dossiers']}),
        ('Informations complémentaires', {'fields': ['chemin_sharepoint', 'nom_fichier'], 'classes': ['collapse']}),
    ]

    @admin.display(description='État du fichier')
    def etat_fichier(self, obj):
        if not obj.disponible:
            return format_html('<span class="file-state missing">{}</span>', 'À déposer')
        if obj.expire:
            return format_html('<span class="file-state expired">{}</span>', 'Expiré')
        return format_html('<span class="file-state available">{}</span>', 'Disponible')

    @admin.display(description='Téléchargement')
    def telechargement(self, obj):
        if not obj.pk or not obj.disponible:
            return 'Aucun fichier disponible'
        return format_html('<a href="{}">{}</a>', reverse('download_document', args=[obj.pk]), obj.nom_fichier or obj.nom)


@admin.register(DolibarrSource, site=admin_site)
class DolibarrSourceAdmin(admin.ModelAdmin):
    form = DolibarrSourceForm
    list_display = ['nom', 'url', 'active', 'cle_enregistree']
    search_fields = ['nom', 'url']
    list_filter = ['active']

    @admin.display(description='Clé API enregistrée', boolean=True)
    def cle_enregistree(self, source):
        return bool(decrypt_key(source.url, source.cle_chiffree))

    @method_decorator(sensitive_post_parameters('cle_api'))
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)


class ReferenceDolibarrInline(admin.TabularInline):
    model = ReferenceDolibarr
    extra = 1


@admin.register(Produit, site=admin_site)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ['reference', 'references_dolibarr_affichees', 'nom', 'marque', 'categorie', 'actif']
    list_filter = ['actif', 'systemes', 'marque', 'categorie']
    search_fields = ['reference', 'references_dolibarr__reference', 'nom', 'description']
    filter_horizontal = ['systemes', 'documents']
    list_select_related = ['marque', 'categorie']
    inlines = [ReferenceDolibarrInline]
    fieldsets = [
        ('Identification du produit', {'fields': ['reference', 'nom', 'marque', 'categorie', 'actif']}),
        ('Systèmes et documentation', {'fields': ['systemes', 'documents']}),
        ('Description', {'fields': ['description'], 'classes': ['collapse']}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('references_dolibarr')

    @admin.display(description='Références Dolibarr')
    def references_dolibarr_affichees(self, produit):
        return ', '.join(reference.reference for reference in produit.references_dolibarr.all())


@admin.register(ExportRecord, site=admin_site)
class ExportAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'projet', 'nombre_produits', 'nombre_fichiers', 'incomplet']
    list_filter = ['incomplet', 'created_at']
    readonly_fields = ['created_at', 'projet', 'nombre_produits', 'nombre_fichiers', 'incomplet']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

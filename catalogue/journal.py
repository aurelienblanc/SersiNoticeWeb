"""Structured events: never record passwords, request bodies, cookies or tokens."""
from django.contrib.admin.models import LogEntry
from django.db.models.signals import post_save

from .models import ActivityEvent, ExportRecord


def record_event(category, event, message, *, level='INFO', details=None):
    return ActivityEvent.objects.create(category=category, event=event, message=str(message)[:1000], level=level, details=details or {})


def catalogue_changed(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.content_type and instance.content_type.app_label == 'catalogue':
        action = {1: 'Ajout', 2: 'Modification', 3: 'Suppression'}.get(instance.action_flag, 'Modification')
        record_event('catalogue', 'catalogue.change', f'{action} : {instance.object_repr}', details={
            'modele': instance.content_type.model, 'objet': instance.object_id,
            'modification': instance.get_change_message(),
        })


def export_created(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        record_event('exports', 'export.created', f'Export : {instance.projet or "Dossier documentaire"}',
                     level='WARNING' if instance.incomplet else 'INFO', details={
                         'produits': instance.nombre_produits, 'fichiers': instance.nombre_fichiers,
                         'incomplet': instance.incomplet,
                     })


def connect_signals():
    post_save.connect(catalogue_changed, sender=LogEntry, dispatch_uid='sersi-catalogue-journal')
    post_save.connect(export_created, sender=ExportRecord, dispatch_uid='sersi-export-journal')

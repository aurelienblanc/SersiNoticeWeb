from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    name = 'catalogue'
    verbose_name = 'Catalogue documentaire'

    def ready(self):
        from .journal import connect_signals
        connect_signals()

from django import forms
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator

from .admin_access import verify_password
from .journal import record_event
from .models import ActivityEvent, AdministrationAccess, MaintenanceSettings


class MaintenanceSettingsForm(forms.ModelForm):
    class Meta:
        model = MaintenanceSettings
        fields = ['automatic_backups', 'backup_time', 'automatic_retention', 'log_retention_days']
        labels = {'automatic_backups': 'Activer la sauvegarde quotidienne', 'backup_time': 'Heure de sauvegarde',
                  'automatic_retention': 'Sauvegardes automatiques à conserver', 'log_retention_days': 'Journaux à conserver (jours)'}
        widgets = {'backup_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'})}

    def clean_automatic_retention(self):
        value = self.cleaned_data['automatic_retention']
        if not 1 <= value <= 100:
            raise forms.ValidationError('Choisissez une valeur entre 1 et 100.')
        return value

    def clean_log_retention_days(self):
        value = self.cleaned_data['log_retention_days']
        if not 7 <= value <= 3650:
            raise forms.ValidationError('Choisissez une durée entre 7 et 3 650 jours.')
        return value


class JournalFilterForm(forms.Form):
    q = forms.CharField(label='Rechercher', max_length=200, required=False)
    level = forms.ChoiceField(label='Niveau', required=False, choices=[('', 'Tous les niveaux'), *ActivityEvent._meta.get_field('level').choices])
    category = forms.ChoiceField(label='Rubrique', required=False, choices=[('', 'Toutes les rubriques'), *ActivityEvent._meta.get_field('category').choices])
    after = forms.DateField(label='Depuis le', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    before = forms.DateField(label='Jusqu’au', required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('after') and data.get('before') and data['after'] > data['before']:
            raise forms.ValidationError('La date de fin doit être postérieure à la date de début.')
        return data


class BackupUploadForm(forms.Form):
    archive = forms.FileField(label='Archive de sauvegarde SERSI Notice', widget=forms.FileInput(attrs={'accept': '.zip'}))

    def clean_archive(self):
        file = self.cleaned_data['archive']
        if file.size > settings.SERSI_BACKUP_UPLOAD_BYTES:
            raise forms.ValidationError('Cette sauvegarde dépasse la taille maximale autorisée.')
        return file


class ConfirmMaintenanceForm(forms.Form):
    password = forms.CharField(label='Mot de passe commun', strip=False, max_length=1024,
                              widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    confirmation = forms.CharField(label='Confirmation', max_length=20)

    def __init__(self, *args, request, word, purge_days=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request, self.word = request, word
        self.fields['confirmation'].label = f'Saisissez « {word} » pour confirmer'
        if purge_days is not None:
            self.fields['days'] = forms.IntegerField(label='Conserver les journaux des derniers jours', initial=purge_days,
                                                    validators=[MinValueValidator(1), MaxValueValidator(3650)])

    def clean_password(self):
        password = self.cleaned_data['password']
        access = AdministrationAccess.objects.get(pk=1)
        valid, blocked = verify_password(self.request, password, access)
        if not valid:
            record_event('security', 'admin.confirmation_failed', 'Confirmation d’une opération de maintenance refusée.', level='WARNING')
            raise forms.ValidationError('Trop de tentatives. Réessayez dans cinq minutes.' if blocked else 'Le mot de passe est incorrect.')
        return password

    def clean_confirmation(self):
        value = self.cleaned_data['confirmation']
        if value != self.word:
            raise forms.ValidationError(f'Saisissez exactement {self.word}.')
        return value

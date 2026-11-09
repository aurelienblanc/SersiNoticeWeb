import re

from django import forms

from .dolibarr_config import MAX_KEY_LENGTH, decrypt_key, encrypt_key, valid_api_key, validate_connection_url
from .models import DolibarrSource, TypeExport


class DolibarrSourceForm(forms.ModelForm):
    cle_api = forms.CharField(
        label='Clé API', required=False, max_length=MAX_KEY_LENGTH,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Laissez vide pour conserver la clé enregistrée. Saisissez une nouvelle clé si vous changez l’adresse.',
    )

    class Meta:
        model = DolibarrSource
        fields = ['nom', 'url', 'cle_api', 'active']

    def clean_url(self):
        return validate_connection_url(self.cleaned_data['url'])

    def clean_cle_api(self):
        key = self.cleaned_data['cle_api']
        if key and not valid_api_key(key):
            raise forms.ValidationError('La clé API contient des caractères invalides.')
        return key

    def clean(self):
        data = super().clean()
        url = data.get('url')
        if url and data.get('active') and 'cle_api' in data:
            if not data['cle_api'] and not decrypt_key(url, self.instance.cle_chiffree):
                self.add_error('cle_api', 'Saisissez une clé API pour activer cette source.')
        return data

    def save(self, commit=True):
        source = super().save(commit=False)
        if key := self.cleaned_data['cle_api']:
            source.cle_chiffree = encrypt_key(source.url, key)
        elif not decrypt_key(source.url, source.cle_chiffree):
            source.cle_chiffree = ''
        if commit:
            source.save()
        return source


class ProposalLookupForm(forms.Form):
    source = forms.ModelChoiceField(
        queryset=DolibarrSource.objects.none(), label='Source Dolibarr', empty_label='Choisir une source',
    )
    reference = forms.RegexField(
        r'^[A-Za-z0-9(][A-Za-z0-9._()/ -]*$', max_length=100,
        label='Numéro de proposition',
        widget=forms.TextInput(attrs={'placeholder': 'Ex. PR2611-00001', 'autocomplete': 'off'}),
        error_messages={'invalid': 'Saisissez le numéro exact de la proposition commerciale.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sources = DolibarrSource.available()
        self.fields['source'].queryset = sources
        first_sources = list(sources.values_list('pk', flat=True)[:2])
        self.has_sources = bool(first_sources)
        if len(first_sources) == 1:
            self.initial['source'] = first_sources[0]

    def clean_reference(self):
        value = self.cleaned_data['reference']
        if re.search(r'(^|/)\.{1,2}(/|$)', value):
            raise forms.ValidationError('Ce numéro de proposition est invalide.')
        return value


class ProposalSelectionForm(forms.Form):
    projet = forms.CharField(max_length=200, required=False, label='Nom du projet')
    client = forms.CharField(max_length=200, required=False, label='Client')
    types_export = forms.ModelMultipleChoiceField(
        TypeExport.objects.all(), label='Documents à inclure', widget=forms.CheckboxSelectMultiple,
    )
    exclure_expires = forms.BooleanField(required=False, label='Exclure les documents expirés')
    confirmer_lignes = forms.BooleanField(
        required=False,
        label='Je confirme la préparation avec les seuls produits reconnus, sans notices pour les lignes signalées.',
    )

    def __init__(self, *args, has_issues=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['confirmer_lignes'].required = has_issues

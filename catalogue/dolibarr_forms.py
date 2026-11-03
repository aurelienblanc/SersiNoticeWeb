import re

from django import forms

from .models import TypeExport


class ProposalLookupForm(forms.Form):
    reference = forms.RegexField(
        r'^[A-Za-z0-9(][A-Za-z0-9._()/ -]*$', max_length=100,
        label='Numéro de proposition',
        widget=forms.TextInput(attrs={'placeholder': 'Ex. PR2611-00001', 'autocomplete': 'off'}),
        error_messages={'invalid': 'Saisissez le numéro exact de la proposition commerciale.'},
    )

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

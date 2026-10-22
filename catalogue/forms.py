from django import forms
from django.db.models import Q

from .models import Marque, Produit, Systeme, TypeExport


class SelectionForm(forms.Form):
    systeme = forms.ModelChoiceField(Systeme.objects.all(), required=False, empty_label='Tous les systèmes')
    marque = forms.ModelChoiceField(Marque.objects.all(), required=False, empty_label='Toutes les marques')
    types_export = forms.ModelMultipleChoiceField(TypeExport.objects.all(), label='Documents à inclure')
    produits = forms.ModelMultipleChoiceField(Produit.objects.all(), label='Produits')
    projet = forms.CharField(max_length=200, required=False, label='Nom du projet')
    client = forms.CharField(max_length=200, required=False, label='Client')
    inclure_inactifs = forms.BooleanField(required=False)
    exclure_expires = forms.BooleanField(required=False, label='Exclure les documents expirés')

    def clean(self):
        data = super().clean()
        products = data.get('produits')
        if products is None:
            return data
        allowed = Produit.objects.filter(pk__in=products.values_list('pk', flat=True))
        if not data.get('inclure_inactifs'):
            allowed = allowed.filter(actif=True)
        if data.get('systeme'):
            allowed = allowed.filter(systemes=data['systeme'])
        if data.get('marque'):
            allowed = allowed.filter(Q(marque=data['marque']) | Q(marque__generique=True))
        if allowed.distinct().count() != products.count():
            raise forms.ValidationError('Certains produits ne correspondent plus aux filtres. Revenez à la sélection.')
        return data

    def selection(self):
        data = self.cleaned_data
        return {
            'produits': list(data['produits'].values_list('pk', flat=True)),
            'types_export': list(data['types_export'].values_list('pk', flat=True)),
            'systeme': data['systeme'].pk if data['systeme'] else '',
            'marque': data['marque'].pk if data['marque'] else '',
            'projet': data['projet'], 'client': data['client'],
            'inclure_inactifs': data['inclure_inactifs'],
            'inclure_expires': not data['exclure_expires'],
        }

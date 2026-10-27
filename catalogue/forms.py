from django import forms
from django.db.models import Q

from .models import Marque, Produit, Systeme, TypeDocument, TypeExport


def _product_description(product):
    suffix = ' · Inactif' if not product.actif else ''
    return f'{product.nom} · {product.marque.nom}{suffix}'


class DocumentProductSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        product = getattr(value, 'instance', None)
        if product is not None:
            option['attrs']['data-brand'] = str(product.marque_id)
            option['attrs']['data-description'] = _product_description(product)
        return option


class DocumentProductField(forms.ModelChoiceField):
    def label_from_instance(self, product):
        return f'{product.reference} · {_product_description(product)}'


class DocumentSearchForm(forms.Form):
    marque = forms.ModelChoiceField(
        Marque.objects.all(), required=False, empty_label='Toutes les marques', label='Marque',
    )
    reference = DocumentProductField(
        Produit.objects.select_related('marque').order_by('reference'),
        to_field_name='reference', required=False, label='Produit',
        empty_label='Tous les produits', widget=DocumentProductSelect,
        error_messages={'invalid_choice': 'Sélectionnez un produit proposé dans la liste.'},
    )
    type_document = forms.ModelChoiceField(
        TypeDocument.objects.all(), required=False,
        empty_label='Tous les types de documents', label='Type de document',
    )

    def clean(self):
        data = super().clean()
        brand, product = data.get('marque'), data.get('reference')
        if brand and product and product.marque_id != brand.pk:
            self.add_error('reference', 'Le produit sélectionné ne correspond pas à cette marque.')
        return data


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

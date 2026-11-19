from django.core import signing
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .dolibarr import (
    DolibarrError, DolibarrRecordType, group_matched_products, match_record, matching_references, source_fingerprint,
)
from .dolibarr_forms import DolibarrLookupForm, DolibarrSelectionForm
from .forms import SelectionForm
from .journal import record_event
from .models import DolibarrSource, TypeExport
from .views import render_selection_preview

IMPORT_SALT = 'sersi-dolibarr-proposal-v3'


@require_http_methods(['GET', 'POST'])
@never_cache
def record_lookup(request):
    form = DolibarrLookupForm(request.POST if request.method == 'POST' else None)
    report = None
    if request.method == 'POST' and form.is_valid():
        source = form.cleaned_data['source']
        record_type = form.cleaned_data['record_type']
        try:
            report = match_record(source, record_type, form.cleaned_data['reference'])
        except DolibarrError as error:
            form.add_error(None, str(error))
            record_event(
                'exports', 'dolibarr.import_failed', f'Lecture Dolibarr impossible pour le type « {record_type.label} ».',
                level='WARNING', details={'source': source.nom},
            )
    if report is None:
        return render(request, 'catalogue/dolibarr.html', {'lookup_form': form},
                      status=400 if request.method == 'POST' else 200)
    payload = {key: report[key] for key in ('reference', 'issues', 'line_count', 'matched_lines', 'product_map')}
    payload['source_id'] = source.pk
    payload['source'] = source_fingerprint(source)
    payload['record_type'] = record_type.value
    token = signing.dumps(payload, salt=IMPORT_SALT, compress=True)
    selection_form = DolibarrSelectionForm(initial={
        'projet': report['reference'], 'types_export': list(TypeExport.objects.values_list('pk', flat=True)),
    }, has_issues=bool(report['issues']))
    record_event(
        'exports', f'dolibarr.{record_type.name.lower()}_loaded',
        f'{record_type.label} {report["reference"]} chargée depuis Dolibarr.',
        details={'source': source.nom, 'produits': len(report['products']), 'lignes_signalees': len(report['issues'])},
    )
    return render(request, 'catalogue/dolibarr.html', {
        'source': source, 'record_type': record_type, 'report': report, 'token': token, 'selection_form': selection_form,
    })


@require_POST
@never_cache
def record_preview(request):
    try:
        payload = signing.loads(request.POST.get('import_token', ''), salt=IMPORT_SALT, max_age=3600)
        source = DolibarrSource.available().defer('cle_chiffree').get(pk=payload['source_id'])
        record_type = DolibarrRecordType(payload.get('record_type', DolibarrRecordType.PROPOSAL))
        references = [reference for _, reference in payload['product_map']]
        matches = list(matching_references(references))
        current = sorted([[match.produit_id, match.reference] for match in matches])
        if payload['source'] != source_fingerprint(source) or not matches or current != sorted(payload['product_map']):
            raise ValueError
        report = {key: payload[key] for key in ('reference', 'issues', 'line_count', 'matched_lines')}
        report['products'] = group_matched_products(matches)
    except (signing.BadSignature, DolibarrSource.DoesNotExist, ValueError, TypeError, KeyError):
        return render(request, 'catalogue/error.html', {
            'message': 'Le récapitulatif a expiré ou ses correspondances ont changé. Rechargez le document depuis Dolibarr.',
        }, status=409)
    form = DolibarrSelectionForm(request.POST, has_issues=bool(report['issues']))
    if not form.is_valid():
        return render(request, 'catalogue/dolibarr.html', {
            'source': source, 'record_type': record_type, 'report': report,
            'token': request.POST.get('import_token'), 'selection_form': form,
        }, status=400)
    data = form.cleaned_data
    products = [item['product'] for item in report['products']]
    selection_form = SelectionForm({
        'produits': [product.pk for product in products],
        'types_export': list(data['types_export'].values_list('pk', flat=True)),
        'projet': data['projet'], 'client': data['client'],
        'inclure_inactifs': any(not product.actif for product in products),
        'exclure_expires': data['exclure_expires'],
    })
    return render_selection_preview(request, selection_form)

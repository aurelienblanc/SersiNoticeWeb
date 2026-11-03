from django.conf import settings
from django.core import signing
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .dolibarr import DolibarrError, match_proposal, source_fingerprint
from .dolibarr_forms import ProposalLookupForm, ProposalSelectionForm
from .forms import SelectionForm
from .journal import record_event
from .models import Produit, TypeExport
from .views import render_selection_preview

IMPORT_SALT = 'sersi-dolibarr-proposal-v1'


def _context(**kwargs):
    return {'erp_name': settings.SERSI_DOLIBARR_NAME, **kwargs}


@require_http_methods(['GET', 'POST'])
@never_cache
def proposal_lookup(request):
    form = ProposalLookupForm(request.POST if request.method == 'POST' else None)
    report = None
    if request.method == 'POST' and form.is_valid():
        try:
            report = match_proposal(form.cleaned_data['reference'])
        except DolibarrError as error:
            form.add_error(None, str(error))
            record_event('exports', 'dolibarr.import_failed', 'Lecture de proposition Dolibarr impossible.', level='WARNING')
    if report is None:
        return render(request, 'catalogue/dolibarr.html', _context(lookup_form=form),
                      status=400 if request.method == 'POST' else 200)
    payload = {key: report[key] for key in ('reference', 'issues', 'line_count', 'matched_lines')}
    payload['source'] = source_fingerprint()
    payload['product_map'] = [[product.pk, product.reference_dolibarr] for product in report['products']]
    token = signing.dumps(payload, salt=IMPORT_SALT, compress=True)
    selection_form = ProposalSelectionForm(initial={
        'projet': report['reference'], 'types_export': list(TypeExport.objects.values_list('pk', flat=True)),
    }, has_issues=bool(report['issues']))
    record_event('exports', 'dolibarr.proposal_loaded', f'Proposition Dolibarr chargée : {report["reference"]}',
                 details={'produits': len(report['products']), 'lignes_signalees': len(report['issues'])})
    return render(request, 'catalogue/dolibarr.html', _context(report=report, token=token, selection_form=selection_form))


@require_POST
@never_cache
def proposal_preview(request):
    try:
        payload = signing.loads(request.POST.get('import_token', ''), salt=IMPORT_SALT, max_age=3600)
        references = [reference for _, reference in payload['product_map']]
        products = list(Produit.objects.filter(reference_dolibarr__in=references).select_related('marque', 'categorie').order_by('reference'))
        current = sorted([[product.pk, product.reference_dolibarr] for product in products])
        if payload['source'] != source_fingerprint() or not products or current != sorted(payload['product_map']):
            raise ValueError
        report = {key: payload[key] for key in ('reference', 'issues', 'line_count', 'matched_lines')}
        report['products'] = products
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        return render(request, 'catalogue/error.html', {
            'message': 'La proposition a expiré ou ses correspondances ont changé. Rechargez-la depuis Dolibarr.',
        }, status=409)
    form = ProposalSelectionForm(request.POST, has_issues=bool(report['issues']))
    if not form.is_valid():
        return render(request, 'catalogue/dolibarr.html', _context(
            report=report, token=request.POST.get('import_token'), selection_form=form,
        ), status=400)
    data = form.cleaned_data
    selection_form = SelectionForm({
        'produits': [product.pk for product in products],
        'types_export': list(data['types_export'].values_list('pk', flat=True)),
        'projet': data['projet'], 'client': data['client'],
        'inclure_inactifs': any(not product.actif for product in products),
        'exclure_expires': data['exclure_expires'],
    })
    return render_selection_preview(request, selection_form)

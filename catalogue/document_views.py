"""Public document search and delivery, independent of dossier preparation."""
from pathlib import Path

from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .exports import safe_filename
from .forms import DocumentSearchForm
from .journal import record_event
from .models import Document, Produit

PAGE_SIZE = 24


@require_GET
@never_cache
def document_library(request):
    form = DocumentSearchForm(request.GET)
    products = Produit.objects.select_related('marque').order_by('reference')
    documents = Document.objects.select_related('type_document').order_by('nom', 'pk')
    valid = form.is_valid()
    if valid:
        brand, reference = form.cleaned_data['marque'], form.cleaned_data['reference']
        if brand:
            products = products.filter(marque=brand)
        if reference:
            products = products.filter(reference__icontains=reference)
        if brand or reference:
            # Both filters must match the same product, even for shared PDFs.
            documents = documents.filter(produits__in=products).distinct()
    else:
        documents = documents.none()
    documents = documents.prefetch_related(Prefetch(
        'produits', queryset=products, to_attr='matching_products',
    ))
    page = Paginator(documents, PAGE_SIZE).get_page(request.GET.get('page'))
    results = []
    for document in page:
        available = document.disponible
        results.append({
            'document': document,
            'available': available,
            'can_view': available and Path(document.fichier.name).suffix.lower() == '.pdf',
            'products': document.matching_products,
        })
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'catalogue/documents.html', {
        'form': form, 'page': page, 'results': results, 'query': query.urlencode(),
        'reference_suggestions': Produit.objects.select_related('marque').order_by('reference'),
    }, status=200 if valid else 400)


def _document_response(pk, *, inline=False):
    document = get_object_or_404(Document, pk=pk)
    if not document.disponible:
        raise Http404('Ce document est indisponible.')
    inline = inline and Path(document.fichier.name).suffix.lower() == '.pdf'
    filename = safe_filename(document.nom_fichier or document.nom + Path(document.fichier.name).suffix)
    try:
        response = FileResponse(
            document.fichier.open('rb'), as_attachment=not inline, filename=filename,
            content_type='application/pdf' if inline else 'application/octet-stream',
        )
    except OSError:
        raise Http404('Ce document est indisponible.')
    response['X-Content-Type-Options'] = 'nosniff'
    event = 'document.viewed' if inline else 'document.downloaded'
    action = 'Consultation' if inline else 'Téléchargement'
    try:
        record_event('exports', event, f'{action} : {document.nom}', details={'document': document.pk})
    except Exception:
        response.close()
        raise
    return response


@require_GET
@never_cache
def view_document(request, pk):
    return _document_response(pk, inline=True)


@require_GET
@never_cache
def download_document(request, pk):
    return _document_response(pk)

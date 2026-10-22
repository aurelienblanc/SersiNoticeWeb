from pathlib import Path

from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .exports import archive_filename, build_archive_tree, build_plan, create_archive, safe_segment
from .forms import SelectionForm
from .journal import record_event
from .models import Categorie, Document, ExportRecord, Marque, Produit, Systeme, TypeExport

TOKEN_SALT = 'sersi-export-selection-v1'


def catalogue_context(form=None):
    form = form or SelectionForm()
    products = Produit.objects.select_related('marque', 'categorie').prefetch_related('systemes').annotate(nombre_documents=Count('documents')).order_by('categorie__ordre', 'categorie__nom', 'nom', 'reference')
    return {
        'form': form, 'produits': products,
        'selected_products': {str(value) for value in (form['produits'].value() or [])},
        'selected_types': {str(value) for value in (form['types_export'].value() or [])} if form.is_bound else {str(pk) for pk in TypeExport.objects.values_list('pk', flat=True)},
        'systemes': Systeme.objects.all(), 'marques': Marque.objects.all(),
        'types_export': TypeExport.objects.all(),
        'categories': Categorie.objects.filter(produit__isnull=False).distinct(),
        'nombre_produits': Produit.objects.filter(actif=True).count(),
        'nombre_documents': Document.objects.count(),
        'nombre_expires': Document.objects.filter(date_expiration__lt=timezone.localdate()).count(),
        'nombre_marques': Marque.objects.count(),
    }


@require_GET
def index(request):
    return render(request, 'catalogue/index.html', catalogue_context())


@require_POST
@never_cache
def preview(request):
    form = SelectionForm(request.POST)
    if not form.is_valid():
        return render(request, 'catalogue/index.html', catalogue_context(form), status=400)
    selection = form.selection()
    try:
        plan = build_plan(form.cleaned_data['produits'], form.cleaned_data['types_export'], selection['inclure_expires'])
    except (ValidationError, OSError) as error:
        form.add_error(None, error if isinstance(error, ValidationError) else 'Impossible de lire les fichiers du serveur.')
        return render(request, 'catalogue/index.html', catalogue_context(form), status=400)
    return render(request, 'catalogue/preview.html', {
        'plan': plan, 'selection': selection, 'produits': form.cleaned_data['produits'],
        'nom_archive': archive_filename(selection),
        'arborescence': build_archive_tree(plan.fichiers),
        'token': signing.dumps(selection, salt=TOKEN_SALT, compress=True),
    })


@require_POST
@never_cache
def download_export(request):
    try:
        selection = signing.loads(request.POST.get('selection', ''), salt=TOKEN_SALT, max_age=3600)
    except signing.BadSignature:
        record_event('exports', 'export.rejected', 'Export refusé : sélection invalide ou expirée.', level='WARNING')
        return render(request, 'catalogue/error.html', {'message': 'La sélection a expiré ou est invalide. Préparez à nouveau votre dossier.'}, status=400)
    # Signed selections keep their inclusion flag, including previews made before
    # the checkbox changed from opting in to opting out of expired documents.
    form = SelectionForm({**selection, 'exclure_expires': not selection['inclure_expires']})
    if not form.is_valid():
        return render(request, 'catalogue/error.html', {'message': 'Le catalogue a changé. Préparez à nouveau votre sélection.'}, status=409)
    products = form.cleaned_data['produits']
    try:
        plan = build_plan(products, form.cleaned_data['types_export'], selection['inclure_expires'])
        if not plan.fichiers:
            raise ValidationError('Aucun fichier disponible pour cette sélection.')
        if plan.indisponibles and request.POST.get('accepter_incomplet') != 'on':
            raise ValidationError('Certains documents sont indisponibles. Confirmez l’export incomplet depuis le récapitulatif.')
        archive, filename = create_archive(plan, selection)
    except (ValidationError, OSError) as error:
        message = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Un fichier ne peut plus être lu. Préparez à nouveau votre dossier.'
        record_event('exports', 'export.rejected', 'Export refusé : ' + message, level='WARNING')
        return render(request, 'catalogue/error.html', {'message': message}, status=409)
    try:
        ExportRecord.objects.create(projet=selection['projet'], nombre_produits=products.count(), nombre_fichiers=len(plan.fichiers), incomplet=bool(plan.indisponibles))
    except Exception:
        archive.close()
        raise
    return FileResponse(archive, as_attachment=True, filename=filename, content_type='application/zip')


@require_GET
@never_cache
def download_document(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if not document.disponible:
        raise Http404('Ce document est indisponible.')
    try:
        response = FileResponse(document.fichier.open('rb'), as_attachment=True,
                                filename=safe_segment(document.nom_fichier or document.nom + Path(document.fichier.name).suffix),
                                content_type='application/octet-stream')
    except OSError:
        raise Http404('Ce document est indisponible.')
    response['X-Content-Type-Options'] = 'nosniff'
    record_event('exports', 'document.downloaded', f'Téléchargement : {document.nom}', details={'document': document.pk})
    return response


@require_GET
@never_cache
def health(request):
    try:
        Systeme.objects.exists()
    except Exception:
        return HttpResponse('unavailable', status=503, content_type='text/plain')
    return HttpResponse('ok', content_type='text/plain')

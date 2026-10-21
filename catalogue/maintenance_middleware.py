from django.http import HttpResponse

from .models import MaintenanceJob


class MaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not (request.path == '/health/' or request.path in ('/admin/login/', '/admin/logout/')
                or request.path.startswith(('/admin/maintenance/', '/static/'))):
            if MaintenanceJob.objects.filter(kind='restore', status='running').exists():
                response = HttpResponse('Une restauration est en cours. Veuillez réessayer dans quelques instants.', status=503)
                response['Retry-After'] = '15'
                return response
        return self.get_response(request)

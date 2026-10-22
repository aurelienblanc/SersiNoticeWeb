from datetime import timedelta
from ipaddress import ip_address

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from .models import AdministrationAccess, AdministrationAttempt

SESSION_KEY = 'sersi_administration'
LIMIT = 5
WINDOW = timedelta(minutes=5)


def access_token(access):
    return salted_hmac('sersi-shared-administration', access.password_hash).hexdigest()


def client_address(request):
    """Trust X-Real-IP only when all requests come through our configured proxy."""
    peer = request.META.get('REMOTE_ADDR', '')
    address = request.META.get('HTTP_X_REAL_IP', peer) if settings.SERSI_TRUST_PROXY else peer
    try:
        return str(ip_address(address))
    except ValueError:
        return peer


@sensitive_variables('password')
def verify_password(request, password, access):
    # Keep only the keyed digest; never persist the client address itself.
    key = salted_hmac('sersi-administration-attempt', client_address(request)).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        attempt, _ = AdministrationAttempt.objects.select_for_update().get_or_create(
            key=key, defaults={'started_at': now},
        )
        if attempt.blocked_until and now < attempt.blocked_until:
            return False, True
        if now - attempt.started_at >= WINDOW:
            attempt.started_at, attempt.failures, attempt.blocked_until = now, 0, None
        if check_password(password, access.password_hash):
            attempt.delete()
            return True, False
        attempt.failures += 1
        if attempt.failures >= LIMIT:
            attempt.blocked_until = now + WINDOW
        attempt.save()
        return False, bool(attempt.blocked_until)


def audit_principal():
    # Django's change journal requires a FK. This non-login account is never
    # exposed as a credential, account-management page or permission choice.
    user, _ = get_user_model().objects.get_or_create(
        username='_sersi_administration',
        defaults={'password': make_password(None), 'is_active': True,
                  'is_staff': True, 'is_superuser': True},
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


class SharedLoginForm(forms.Form):
    password = forms.CharField(
        label='Mot de passe commun', max_length=1024, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'autofocus': True}),
    )


class SharedPasswordChangeForm(forms.Form):
    current_password = forms.CharField(label='Mot de passe actuel', strip=False, max_length=1024,
                                      widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    new_password = forms.CharField(label='Nouveau mot de passe commun', strip=False, max_length=1024,
                                  widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                                  help_text='Au moins 12 caractères.')
    confirmation = forms.CharField(label='Confirmer le nouveau mot de passe', strip=False, max_length=1024,
                                   widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, access, **kwargs):
        super().__init__(*args, **kwargs)
        self.access = access

    def clean_current_password(self):
        password = self.cleaned_data['current_password']
        if not check_password(password, self.access.password_hash):
            raise forms.ValidationError('Le mot de passe actuel est incorrect.')
        return password

    def clean_new_password(self):
        password = self.cleaned_data['new_password']
        validate_password(password)
        return password

    def clean(self):
        data = super().clean()
        if data.get('new_password') and data.get('confirmation') != data['new_password']:
            self.add_error('confirmation', 'Les deux mots de passe doivent être identiques.')
        return data

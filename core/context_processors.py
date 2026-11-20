"""Общие данные для всех шаблонов: профиль мастера и версия статики."""

from django.conf import settings


def sfera(request):
    user = getattr(request, "user", None)
    profile = None
    if user is not None and user.is_authenticated:
        from .models import MasterProfile

        profile = MasterProfile.for_user(user)
    return {
        "profile": profile,
        "asset_version": getattr(settings, "ASSET_VERSION", "1"),
    }

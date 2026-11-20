"""Автоматическое создание профиля мастера при регистрации пользователя."""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_master_profile(sender, instance, created, **kwargs):
    """Каждому новому User — профиль и стартовая воронка «Быстрые услуги»."""
    if not created:
        return

    from core.models import MasterProfile, unique_slug_for

    if MasterProfile.objects.filter(user=instance).exists():
        return

    MasterProfile.objects.create(
        user=instance,
        slug=unique_slug_for(instance.get_username()),
        business_name=instance.get_username(),
    )

    from shop.models import PipelineStage

    PipelineStage.seed_defaults(instance)

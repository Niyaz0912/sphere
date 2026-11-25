"""Сигналы для удаления файлов фотографий услуг."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ServicePhoto


@receiver(post_delete, sender=ServicePhoto)
def delete_service_photo_file(sender, instance, **kwargs):
    """Удаляет файл с диска после удаления записи из базы."""
    if instance.image and instance.image.name:
        instance.image.storage.delete(instance.image.name)

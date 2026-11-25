from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"
    verbose_name = "Воронка, услуги и заказы"

    def ready(self):
        from . import signals  # noqa: F401  — удаление файлов фото услуг


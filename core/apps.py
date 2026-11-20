from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Профили и клиенты"

    def ready(self):
        from . import signals  # noqa: F401  — подписываемся на создание User

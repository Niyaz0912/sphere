#!/usr/bin/env python
"""Создаёт мастера admin или сбрасывает ему пароль на admin123."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - не критично для работы скрипта
        pass

    try:
        import django
    except ImportError:
        print("Django не установлен.")
        print("Установите зависимости: pip install -r requirements.txt")
        return 1

    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.management import call_command

    # На случай первого запуска: создаём таблицы, если их ещё нет.
    call_command("migrate", verbosity=0, interactive=False)

    from core.models import MasterProfile

    User = get_user_model()
    username = "admin"
    user, created = User.objects.get_or_create(username=username)
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.set_password("admin123")
    user.save()

    profile = MasterProfile.for_user(user)
    if not profile.business_name:
        profile.business_name = "Сфера"
        profile.save(update_fields=["business_name", "updated_at"])

    print("=" * 52)
    print(("Создан мастер" if created else "Пароль мастера обновлён"))
    print(f"  логин:  {username}")
    print("  пароль: admin123")
    print(f"  страница: {profile.get_absolute_url()}")
    print("=" * 52)
    print("Запуск: python manage.py runserver")
    print("Вход:   http://127.0.0.1:8000/accounts/login/")
    print("Демо-данные: python manage.py seed_demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

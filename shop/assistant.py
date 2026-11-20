"""«Умный помощник»: правила, которые подсвечивают деньги и зависшие записи."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Max
from django.urls import reverse
from django.utils import timezone

from core.models import Client
from core.templatetags.sfera import rub

from .models import Order

STALE_DAYS = 3
SLEEPING_DAYS = 90


def _plural(number: int, one: str, few: str, many: str) -> str:
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        word = one
    elif 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        word = few
    else:
        word = many
    return f"{number} {word}"


def _reminder(client, profile) -> str:
    business = profile.display_name if profile else "Сфера"
    phone = (getattr(profile, "phone", "") or "").strip()
    tail = f" Позвоните или напишите: {phone}." if phone else ""
    return (
        f"Здравствуйте, {client.short_name}! Это {business}. "
        f"Вы давно к нам не заглядывали — будем рады видеть вас снова.{tail}"
    )


def build_suggestions(owner, profile=None, now=None) -> list[dict]:
    """До трёх карточек-подсказок: долги, зависшие заявки, спящие клиенты."""
    now = now or timezone.now()
    suggestions: list[dict] = []

    # 1. Долги по завершённым заказам.
    debts = list(
        Order.objects.filter(
            owner=owner,
            stage__is_final=True,
            total_amount__gt=F("paid_amount"),
        )
        .select_related("client", "stage")
        .order_by("-scheduled_at")
    )
    if debts:
        debt_total = sum((order.debt_amount for order in debts), Decimal("0.00"))
        first = debts[0]
        debts_label = _plural(
            len(debts),
            "завершённый заказ",
            "завершённых заказа",
            "завершённых заказов",
        )
        suggestions.append(
            {
                "kind": "debt",
                "icon": "wallet",
                "title": "Остались неоплаченные заказы",
                "text": (
                    f"{debts_label} с долгом на {rub(debt_total)}. "
                    f"Ближайший: {first.client.name} — {rub(first.debt_amount)}."
                ),
                "url": reverse("shop:dashboard") + "?view=list&filter=done",
                "action_label": "Открыть завершённые",
                "items": [],
            }
        )

    # 2. Заявки без движения больше трёх дней.
    stale_qs = (
        Order.objects.filter(
            owner=owner,
            stage__is_final=False,
            updated_at__lt=now - timedelta(days=STALE_DAYS),
        )
        .select_related("client", "stage")
        .order_by("updated_at")
    )
    stale_count = stale_qs.count()
    if stale_count:
        oldest = stale_qs.first()
        days = max((now - oldest.updated_at).days, STALE_DAYS)
        suggestions.append(
            {
                "kind": "stale",
                "icon": "clock",
                "title": "Заявки зависли",
                "text": (
                    f"{_plural(stale_count, 'заявка', 'заявки', 'заявок')} без движения "
                    f"больше {STALE_DAYS} дней. Дольше всех ждёт {oldest.client.name} — "
                    f"{_plural(days, 'день', 'дня', 'дней')} на этапе «{oldest.stage.name}»."
                ),
                "url": reverse("shop:dashboard") + "?view=list&filter=active",
                "action_label": "Показать активные",
                "items": [],
            }
        )

    # 3. «Спящие» клиенты: последний визит больше 90 дней назад.
    cutoff = now - timedelta(days=SLEEPING_DAYS)
    sleeping_qs = (
        Client.objects.filter(owner=owner)
        .annotate(last_visit=Max("orders__scheduled_at"))
        .filter(last_visit__lt=cutoff)
        .order_by("last_visit")
    )
    sleeping_count = sleeping_qs.count()
    if sleeping_count:
        preview = []
        for client in sleeping_qs[:3]:
            days = max((now - client.last_visit).days, SLEEPING_DAYS)
            preview.append(
                {
                    "name": client.name,
                    "phone": client.phone,
                    "days": days,
                    "reminder": _reminder(client, profile),
                }
            )
        oldest = preview[0]
        suggestions.append(
            {
                "kind": "sleeping",
                "icon": "sparkles",
                "title": "Клиенты заскучали",
                "text": (
                    f"{_plural(sleeping_count, 'клиент', 'клиента', 'клиентов')} "
                    f"не было больше {SLEEPING_DAYS} дней. Давний визит: "
                    f"{oldest['name']} — {_plural(oldest['days'], 'день', 'дня', 'дней')} назад. "
                    "Скопируйте напоминание и отправьте в мессенджер."
                ),
                "url": reverse("core:client_list"),
                "action_label": "Открыть клиентов",
                "items": preview,
            }
        )

    return suggestions[:3]

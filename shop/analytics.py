"""Аналитика мастера: выручка, прибыль, оплаты и топ услуг за период."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import Order

PERIODS = [
    ("today", "Сегодня"),
    ("week", "Неделя"),
    ("month", "Месяц"),
]
ZERO = Decimal("0.00")


def _bounds(period: str):
    """Календарные границы периода по локальному времени."""
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = today - timedelta(days=6)
    elif period == "month":
        start = today - timedelta(days=29)
    else:
        start = today
    return start, today + timedelta(days=1)


def build_analytics(owner, period: str = "today") -> dict:
    periods = dict(PERIODS)
    if period not in periods:
        period = "today"

    start, end = _bounds(period)
    orders = list(
        Order.objects.filter(
            owner=owner,
            scheduled_at__gte=start,
            scheduled_at__lt=end,
        ).select_related("service", "stage")
    )

    revenue = sum((order.paid_amount for order in orders), ZERO)
    paid_orders = [order for order in orders if order.paid_amount > 0]
    # Себестоимость материалов учитываем по визитам, где уже были деньги.
    cost = sum((order.cost_amount for order in paid_orders), ZERO)
    profit = revenue - cost
    margin = (profit / revenue * 100) if revenue > 0 else ZERO
    avg_check = (revenue / len(paid_orders)) if paid_orders else ZERO
    debt_total = sum((order.debt_amount for order in orders), ZERO)

    payment = {
        Order.PAYMENT_CASH: {"total": ZERO, "count": 0},
        Order.PAYMENT_CARD: {"total": ZERO, "count": 0},
        "other": {"total": ZERO, "count": 0},
    }
    top: dict[str, dict] = {}
    missing_cost = 0

    for order in paid_orders:
        method = (
            order.payment_method
            if order.payment_method in payment
            else "other"
        )
        payment[method]["total"] += order.paid_amount
        payment[method]["count"] += 1

        name = order.service_name or "Без услуги"
        row = top.setdefault(
            name,
            {"name": name, "count": 0, "revenue": ZERO, "profit": ZERO},
        )
        row["count"] += 1
        row["revenue"] += order.paid_amount
        row["profit"] += order.profit_amount
        if order.service_id and order.service and order.service.cost_price <= 0:
            missing_cost += 1

    top_services = sorted(
        top.values(),
        key=lambda row: (-row["revenue"], -row["count"], row["name"].lower()),
    )[:5]

    completed = [order for order in orders if order.stage.is_final]

    return {
        "period": period,
        "period_label": periods[period],
        "periods": PERIODS,
        "finance": {
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": margin,
            "avg_check": avg_check,
            "paid_orders": len(paid_orders),
            "orders_count": len(orders),
            "completed_count": len(completed),
            "debt_total": debt_total,
            "cash": payment[Order.PAYMENT_CASH],
            "card": payment[Order.PAYMENT_CARD],
            "other": payment["other"],
            "missing_cost_count": missing_cost,
        },
        "top_services": top_services,
    }

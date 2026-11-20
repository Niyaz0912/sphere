"""Рабочий стол, заказы, услуги, аналитика и Excel-обмен."""

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import Client, MasterProfile
from core.templatetags.sfera import rub

from . import analytics as analytics_service
from .assistant import build_suggestions
from .excel import export_workbook, import_workbook, template_workbook
from .forms import OrderForm, PaymentForm, ServiceForm
from .models import Order, PipelineStage, Service

logger = logging.getLogger(__name__)

LIST_FILTERS = [
    ("active", "Все активные"),
    ("today", "Сегодня"),
    ("tomorrow", "Завтра"),
    ("done", "Завершённые"),
]
KANBAN_LIMIT = 80


# --------------------------------------------------------------------------- #
# Служебные помощники
# --------------------------------------------------------------------------- #


def _wants_json(request) -> bool:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    return "application/json" in request.headers.get("accept", "")


def _form_errors(form) -> dict:
    errors = {}
    for field, field_errors in form.errors.items():
        if field == "__all__":
            continue
        if field_errors:
            errors[field] = field_errors[0]
    return errors


def _form_error(form) -> str:
    for field_errors in form.errors.values():
        if field_errors:
            return field_errors[0]
    return "Проверьте поля формы."


def _safe_next(request):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def _redirect_back(request, default: str = "shop:dashboard"):
    return redirect(_safe_next(request) or default)


def _local_day_start(day):
    naive = datetime.combine(day, time.min)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _next_hour():
    moment = timezone.localtime() + timedelta(hours=1)
    return moment.replace(minute=0, second=0, microsecond=0)


def _attach_stage_links(orders, stages):
    """Проставляет next_stage_obj, чтобы шаблон не делал запрос на каждую карточку."""
    next_map = {
        stages[index].pk: stages[index + 1] for index in range(len(stages) - 1)
    }
    for order in orders:
        order.next_stage_obj = next_map.get(order.stage_id)


def _ensure_stages(user):
    stages = list(PipelineStage.objects.filter(owner=user).order_by("order", "id"))
    if not stages:
        PipelineStage.seed_defaults(user)
        stages = list(PipelineStage.objects.filter(owner=user).order_by("order", "id"))
    return stages


# --------------------------------------------------------------------------- #
# Рабочий стол
# --------------------------------------------------------------------------- #


@login_required
def dashboard(request):
    user = request.user
    profile = MasterProfile.for_user(user)
    stages = _ensure_stages(user)

    view_mode = request.GET.get("view") or request.GET.get("mode") or "kanban"
    if view_mode not in ("kanban", "list"):
        view_mode = "kanban"

    filter_key = request.GET.get("filter") or "active"
    if filter_key not in dict(LIST_FILTERS):
        filter_key = "active"

    orders = list(
        Order.objects.filter(owner=user)
        .select_related("client", "service", "stage")
        .order_by("scheduled_at", "id")
    )
    _attach_stage_links(orders, stages)

    columns = []
    for stage in stages:
        items = [order for order in orders if order.stage_id == stage.pk]
        items.sort(
            key=lambda order: (order.scheduled_at, order.pk),
            reverse=stage.is_final,
        )
        columns.append(
            {
                "stage": stage,
                "orders": items[:KANBAN_LIMIT],
                "count": len(items),
                "total": sum((order.total_amount for order in items), Decimal("0.00")),
                "debt": sum((order.debt_amount for order in items), Decimal("0.00")),
                "hidden": max(len(items) - KANBAN_LIMIT, 0),
            }
        )

    today = timezone.localdate()
    today_start = _local_day_start(today)
    today_end = today_start + timedelta(days=1)

    if filter_key == "today":
        list_orders = [
            order
            for order in orders
            if today_start <= order.scheduled_at < today_end
        ]
    elif filter_key == "tomorrow":
        tomorrow_start = today_start + timedelta(days=1)
        list_orders = [
            order
            for order in orders
            if tomorrow_start <= order.scheduled_at < tomorrow_start + timedelta(days=1)
        ]
    elif filter_key == "done":
        list_orders = [order for order in orders if order.stage.is_final]
    else:
        list_orders = [order for order in orders if not order.stage.is_final]

    if filter_key == "done":
        list_orders.sort(key=lambda order: order.scheduled_at, reverse=True)

    active_orders = [order for order in orders if not order.stage.is_final]
    month_start = _local_day_start(today.replace(day=1))
    month_end = _local_day_start(
        (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    )
    has_services = Service.objects.filter(owner=user).exists()
    stats = {
        "active": len(active_orders),
        "today": sum(
            1 for order in orders if today_start <= order.scheduled_at < today_end
        ),
        "debt": sum((order.debt_amount for order in orders), Decimal("0.00")),
        "paid_month": sum(
            (
                order.paid_amount
                for order in orders
                if month_start <= order.scheduled_at < month_end
            ),
            Decimal("0.00"),
        ),
    }

    return render(
        request,
        "shop/dashboard.html",
        {
            "profile": profile,
            "view_mode": view_mode,
            "filter_key": filter_key,
            "list_filters": LIST_FILTERS,
            "columns": columns,
            "orders": list_orders,
            "stats": stats,
            "suggestions": build_suggestions(user, profile),
            "order_form": OrderForm(owner=user),
            "payment_form": PaymentForm(),
            "today": today,
            "has_services": has_services,
            "public_url": request.build_absolute_uri(profile.get_absolute_url()),
        },
    )


@login_required
def order_create(request):
    user = request.user
    stages = _ensure_stages(user)
    clients = list(Client.objects.filter(owner=user).order_by("name"))

    initial = {
        "stage": stages[0] if stages else None,
        "scheduled_at": _next_hour(),
        "payment_method": Order.PAYMENT_NONE,
    }
    client_id = request.GET.get("client")
    if client_id:
        selected = next(
            (client for client in clients if str(client.pk) == str(client_id)), None
        )
        if selected is not None:
            initial["client"] = selected

    if request.method == "POST":
        form = OrderForm(request.POST, owner=user)
        if form.is_valid():
            order = form.save(commit=False)
            order.owner = user
            order.save()
            messages.success(
                request,
                f"Запись создана: {order.client.name} · "
                f"{timezone.localtime(order.scheduled_at):%d.%m.%Y %H:%M}.",
            )
            return redirect("shop:dashboard")
    else:
        form = OrderForm(owner=user, initial=initial)

    return render(
        request,
        "shop/order_form.html",
        {
            "form": form,
            "stages": stages,
            "clients": clients,
            "title": "Новая запись",
        },
    )


@login_required
@require_POST
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk, owner=request.user)
    form = OrderForm(request.POST, instance=order, owner=request.user)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": _form_error(form),
                "errors": _form_errors(form),
            },
            status=400,
        )
    form.save()
    return JsonResponse(
        {
            "ok": True,
            "message": "Запись обновлена.",
            "redirect": reverse("shop:dashboard"),
        }
    )


@login_required
@require_POST
def order_pay(request, pk):
    order = get_object_or_404(Order, pk=pk, owner=request.user)
    if order.debt_amount <= 0:
        return JsonResponse(
            {"ok": False, "error": "Этот заказ уже полностью оплачен.", "errors": {}},
            status=400,
        )

    form = PaymentForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": _form_error(form),
                "errors": _form_errors(form),
            },
            status=400,
        )

    amount = form.cleaned_data["amount"]
    if amount > order.debt_amount:
        message = f"Сумма больше долга {rub(order.debt_amount)}. Уменьшите платёж."
        return JsonResponse(
            {"ok": False, "error": message, "errors": {"amount": message}},
            status=400,
        )

    order.paid_amount += amount
    order.payment_method = form.cleaned_data["payment_method"]
    order.save(update_fields=["paid_amount", "payment_method", "updated_at"])

    message = f"Принято {rub(amount)}. Остаток долга: {rub(order.debt_amount)}."
    return JsonResponse(
        {
            "ok": True,
            "message": message,
            "paid_amount": str(order.paid_amount),
            "debt_amount": str(order.debt_amount),
            "redirect": reverse("shop:dashboard"),
        }
    )


@login_required
@require_POST
def order_advance(request, pk):
    order = get_object_or_404(Order, pk=pk, owner=request.user)
    next_stage = order.next_stage()

    if next_stage is None:
        message = "Запись уже на последнем этапе воронки."
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.info(request, message)
        return _redirect_back(request)

    order.stage = next_stage
    order.save(update_fields=["stage", "updated_at"])
    message = f"{order.client.name}: этап «{next_stage.name}»."
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "stage": next_stage.name,
                "redirect": reverse("shop:dashboard"),
            }
        )
    messages.success(request, message)
    return _redirect_back(request)


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #


@login_required
def service_list(request):
    user = request.user
    services = list(Service.objects.filter(owner=user).order_by("name"))
    profile = MasterProfile.for_user(user)
    return render(
        request,
        "shop/services.html",
        {
            "services": services,
            "service_form": ServiceForm(owner=user),
            "active_count": sum(1 for service in services if service.is_active),
            "profile": profile,
            "public_url": request.build_absolute_uri(profile.get_absolute_url()),
            "show_onboarding": not services,
        },
    )


@login_required
@require_POST
def service_save(request):
    user = request.user
    service_id = (request.POST.get("id") or "").strip()
    instance = None
    if service_id:
        if not service_id.isdigit():
            return JsonResponse(
                {"ok": False, "error": "Услуга не найдена.", "errors": {}}, status=404
            )
        instance = get_object_or_404(Service, pk=service_id, owner=user)

    form = ServiceForm(request.POST, instance=instance, owner=user)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": _form_error(form),
                "errors": _form_errors(form),
            },
            status=400,
        )

    service = form.save(commit=False)
    service.owner = user
    service.save()
    return JsonResponse(
        {
            "ok": True,
            "message": (
                "Услуга обновлена: " if instance else "Услуга добавлена: "
            )
            + service.name,
            "redirect": reverse("shop:services"),
        }
    )


@login_required
@require_POST
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk, owner=request.user)
    name = service.name
    service.delete()
    return JsonResponse(
        {
            "ok": True,
            "message": f"Услуга удалена: {name}",
            "redirect": reverse("shop:services"),
        }
    )


@login_required
def service_export(request):
    stream = export_workbook(request.user)
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"sfera-services-{timezone.localdate():%Y%m%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def service_template(request):
    stream = template_workbook()
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        'attachment; filename="sfera-services-template.xlsx"'
    )
    return response


@login_required
def service_import(request):
    result = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, "Выберите файл .xlsx.")
        elif not upload.name.lower().endswith(".xlsx"):
            messages.error(request, "Поддерживаются только файлы .xlsx.")
        else:
            try:
                imported = import_workbook(upload, request.user)
            except Exception as error:  # noqa: BLE001 - показываем причину пользователю
                logger.exception("Импорт услуг не удался")
                messages.error(request, f"Не удалось прочитать файл: {error}")
            else:
                logger.info(
                    "Импорт услуг: всего %s, создано %s, обновлено %s, пропущено %s",
                    imported["total"],
                    imported["created"],
                    imported["updated"],
                    imported["skipped"],
                )
                request.session["service_import_result"] = imported
                return redirect("shop:service_import")
    else:
        result = request.session.pop("service_import_result", None)

    return render(
        request,
        "shop/import.html",
        {"result": result},
    )


# --------------------------------------------------------------------------- #
# Аналитика
# --------------------------------------------------------------------------- #


@login_required
def analytics(request):
    period = request.GET.get("period", "today")
    context = analytics_service.build_analytics(request.user, period)
    return render(request, "shop/analytics.html", context)

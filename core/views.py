"""Профиль мастера, клиентская база, настройки и публичная страница."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from shop.models import Order, PipelineStage, PromoOffer, Service

from .forms import ClientForm, MasterProfileForm, PublicBookingForm, RegisterForm
from .models import Client, MasterProfile


# --------------------------------------------------------------------------- #
# Главная страница площадки
# --------------------------------------------------------------------------- #


def home(request):
    """Публичная витрина «Сферы»: описание, кнопки входа и компании."""
    if request.user.is_authenticated:
        return redirect("shop:dashboard")

    companies = list(
        MasterProfile.objects.filter(
            is_public=True,
            user__is_active=True,
        )
        .select_related("user")
        .annotate(
            service_count=Count(
                "user__services",
                filter=Q(user__services__is_active=True),
            )
        )
        .order_by("-created_at")
    )
    return render(
        request,
        "core/home.html",
        {
            "companies": companies,
            "companies_count": len(companies),
        },
    )


# --------------------------------------------------------------------------- #
# Регистрация
# --------------------------------------------------------------------------- #


def register(request):
    """Регистрация нового мастера. Профиль и воронка создаются автоматически."""
    if request.user.is_authenticated:
        return redirect("shop:dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            profile = MasterProfile.for_user(user)
            messages.success(
                request,
                f"Добро пожаловать, {profile.display_name}! "
                "Начните с первой услуги — она появится на вашей странице.",
            )
            return redirect(f"{reverse('shop:services')}?onboarding=1")
    else:
        form = RegisterForm()

    return render(request, "core/register.html", {"form": form})


# --------------------------------------------------------------------------- #
# Клиенты
# --------------------------------------------------------------------------- #


@login_required
def client_list(request):
    query = (request.GET.get("q") or "").strip()
    clients = list(
        Client.objects.filter(owner=request.user)
        .annotate(
            orders_count=Count("orders"),
            paid_total=Sum("orders__paid_amount"),
        )
        .order_by("-created_at")
    )
    if query:
        needle = query.casefold()
        clients = [
            client
            for client in clients
            if needle in client.name.casefold()
            or needle in client.phone.casefold()
            or needle in (client.identifier or "").casefold()
        ]

    total_revenue = sum((client.paid_total or 0 for client in clients), start=0)
    return render(
        request,
        "core/client_list.html",
        {
            "clients": clients,
            "query": query,
            "total_revenue": total_revenue,
        },
    )


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    orders = list(
        client.orders.select_related("service", "stage").order_by(
            "-scheduled_at", "-created_at"
        )
    )
    total_paid = sum((order.paid_amount for order in orders), start=0)
    total_billed = sum((order.total_amount for order in orders), start=0)
    completed = [order for order in orders if order.stage.is_final]
    now = timezone.now()
    past_visits = [
        order.scheduled_at for order in orders if order.scheduled_at <= now
    ]
    last_visit = max(past_visits) if past_visits else None

    return render(
        request,
        "core/client_detail.html",
        {
            "client": client,
            "orders": orders,
            "total_paid": total_paid,
            "total_billed": total_billed,
            "debt": max(total_billed - total_paid, 0),
            "completed_count": len(completed),
            "last_visit": last_visit,
        },
    )


@login_required
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST, owner=request.user)
        if form.is_valid():
            client = form.save(commit=False)
            client.owner = request.user
            client.save()
            messages.success(request, f"Клиент добавлен: {client.name}")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = ClientForm(owner=request.user)
    return render(
        request,
        "core/client_form.html",
        {"form": form, "title": "Новый клиент", "is_edit": False},
    )


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client, owner=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Карточка клиента обновлена.")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = ClientForm(instance=client, owner=request.user)
    return render(
        request,
        "core/client_form.html",
        {
            "form": form,
            "title": "Редактирование клиента",
            "is_edit": True,
            "client": client,
        },
    )


@login_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    if client.orders.exists():
        messages.error(
            request,
            "Нельзя удалить клиента с историей заказов. Сначала удалите или перенесите записи.",
        )
        return redirect("core:client_detail", pk=client.pk)

    if request.method == "POST":
        name = client.name
        client.delete()
        messages.success(request, f"Клиент удалён: {name}")
        return redirect("core:client_list")
    return render(request, "core/client_confirm_delete.html", {"client": client})


# --------------------------------------------------------------------------- #
# Настройки публичной страницы и воронки
# --------------------------------------------------------------------------- #


def _stage_name_taken(owner, name: str, exclude_pk=None) -> bool:
    queryset = PipelineStage.objects.filter(owner=owner)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    needle = name.strip().casefold()
    return any(stage.name.strip().casefold() == needle for stage in queryset)


def _parse_order(value, fallback: int) -> int:
    try:
        order = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(order, 0)


def _owner_stage(user, raw_id):
    """Этап мастера по id из формы; None для мусорного или чужого id."""
    try:
        pk = int(raw_id)
    except (TypeError, ValueError):
        return None
    return PipelineStage.objects.filter(owner=user, pk=pk).first()


@login_required
def settings_view(request):
    """Настройки публичной страницы и этапов воронки."""
    profile = MasterProfile.for_user(request.user)
    form = MasterProfileForm(instance=profile)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "profile":
            form = MasterProfileForm(request.POST, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Настройки публичной страницы сохранены.")
                return redirect("settings")
            messages.error(request, "Проверьте выделенные поля.")

        elif action == "stage_add":
            name = (request.POST.get("new_name") or "").strip()
            color = request.POST.get("new_color") or PipelineStage.COLOR_PRIMARY
            if color not in PipelineStage.COLOR_VALUES:
                color = PipelineStage.COLOR_PRIMARY
            default_order = (
                PipelineStage.objects.filter(owner=request.user).aggregate(
                    max_order=Max("order")
                )["max_order"]
                or 0
            )
            order = _parse_order(request.POST.get("new_order"), default_order + 1)
            is_final = request.POST.get("new_is_final") == "on"
            if not name:
                messages.error(request, "Введите название нового этапа.")
            elif _stage_name_taken(request.user, name):
                messages.error(request, "Этап с таким названием уже есть.")
            else:
                PipelineStage.objects.create(
                    owner=request.user,
                    name=name,
                    color=color,
                    order=order,
                    is_final=is_final,
                )
                messages.success(request, f"Этап добавлен: {name}")
            return redirect("settings")

        elif action == "stage_update":
            stage = _owner_stage(request.user, request.POST.get("stage_id"))
            if stage is None:
                messages.error(request, "Этап не найден.")
                return redirect("settings")

            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "Название этапа не может быть пустым.")
            elif _stage_name_taken(request.user, name, exclude_pk=stage.pk):
                messages.error(request, "Этап с таким названием уже есть.")
            else:
                color = request.POST.get("color") or PipelineStage.COLOR_PRIMARY
                stage.name = name
                stage.color = (
                    color
                    if color in PipelineStage.COLOR_VALUES
                    else PipelineStage.COLOR_PRIMARY
                )
                stage.order = _parse_order(request.POST.get("order"), stage.order)
                stage.is_final = request.POST.get("is_final") == "on"
                stage.save(update_fields=["name", "color", "order", "is_final"])
                messages.success(request, "Этап обновлён.")
            return redirect("settings")

        elif action == "stage_delete":
            stage = _owner_stage(request.user, request.POST.get("stage_id"))
            if stage is None:
                messages.error(request, "Этап не найден.")
            elif stage.orders.exists():
                messages.error(
                    request,
                    "Нельзя удалить этап, в котором есть записи. "
                    "Сначала переведите их на другой этап.",
                )
            elif PipelineStage.objects.filter(owner=request.user).count() <= 1:
                messages.error(request, "Должен остаться хотя бы один этап воронки.")
            else:
                name = stage.name
                stage.delete()
                messages.success(request, f"Этап удалён: {name}")
            return redirect("settings")

        elif action == "load_template":
            key = request.POST.get("template") or ""
            if key not in PipelineStage.TEMPLATES:
                messages.error(request, "Неизвестный шаблон воронки.")
            else:
                added = PipelineStage.apply_template(request.user, key)
                title = PipelineStage.TEMPLATES[key]["title"]
                if added:
                    messages.success(
                        request, f"Шаблон «{title}» загружен: добавлено этапов — {added}."
                    )
                else:
                    messages.info(
                        request, f"Шаблон «{title}» уже применён — все этапы на месте."
                    )
            return redirect("settings")

    stages = list(
        PipelineStage.objects.filter(owner=request.user).order_by("order", "id")
    )
    return render(
        request,
        "core/settings.html",
        {
            "profile": profile,
            "form": form,
            "stages": stages,
            "colors": PipelineStage.COLORS,
            "templates": PipelineStage.TEMPLATES,
            "public_url": request.build_absolute_uri(profile.get_absolute_url()),
        },
    )


# --------------------------------------------------------------------------- #
# Публичная страница мастера
# --------------------------------------------------------------------------- #


def public_master(request, slug):
    """Страница компании /s/<slug>/ — доступна без входа."""
    profile = get_object_or_404(
        MasterProfile.objects.select_related("user"), slug=slug
    )
    owner = profile.user
    services_qs = (
        Service.objects.filter(owner=owner, is_active=True)
        .prefetch_related("photos")
        .order_by("price", "name")
    )
    services = list(services_qs)
    stages = list(
        PipelineStage.objects.filter(owner=owner).order_by("order", "id")
    )

    today = timezone.localdate()
    active_promos = list(
        PromoOffer.objects.filter(owner=owner, is_active=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=today))
        .order_by("-is_featured", "-created_at", "-id")
    )
    featured_promo = next(
        (promo for promo in active_promos if promo.is_featured), None
    )
    partner_promos = [
        promo for promo in active_promos if promo is not featured_promo
    ]

    if request.method == "POST":
        form = PublicBookingForm(request.POST, services=services_qs)
        if form.is_valid():
            # Ловушка для ботов: поле скрыто от людей.
            if form.cleaned_data.get("website"):
                return redirect(f"{profile.get_absolute_url()}?booked=1")

            service = form.cleaned_data["service"]
            scheduled_at = form.cleaned_data["scheduled_at"]

            with transaction.atomic():
                client = Client.find_by_phone(owner, form.cleaned_data["phone"])
                if client is None:
                    client = Client.objects.create(
                        owner=owner,
                        name=form.cleaned_data["name"],
                        phone=form.cleaned_data["phone"],
                    )

                stage = stages[0] if stages else None
                if stage is None:
                    stage = PipelineStage.objects.create(
                        owner=owner,
                        name="Новая заявка",
                        order=1,
                        color=PipelineStage.COLOR_PRIMARY,
                    )

                Order.objects.create(
                    owner=owner,
                    client=client,
                    service=service,
                    service_name=service.name,
                    stage=stage,
                    scheduled_at=scheduled_at,
                    total_amount=service.price,
                    paid_amount=0,
                    payment_method=Order.PAYMENT_NONE,
                    work_details="",
                )
            return redirect(f"{profile.get_absolute_url()}?booked=1")
    else:
        initial = {}
        selected = (request.GET.get("service") or "").strip()
        if selected.isdigit() and any(
            str(service.pk) == selected for service in services
        ):
            initial["service"] = int(selected)
        form = PublicBookingForm(services=services_qs, initial=initial)

    return render(
        request,
        "core/public_master.html",
        {
            "profile": profile,
            "services": services,
            "form": form,
            "booked": request.GET.get("booked") == "1",
            "promos": active_promos,
            "featured_promo": featured_promo,
            "partner_promos": partner_promos,
        },
    )

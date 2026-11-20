"""Этапы воронки, услуги и заказы Сфера."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class PipelineStage(models.Model):
    """Настраиваемый мастером этап воронки (колонка канбана)."""

    COLOR_PRIMARY = "primary"
    COLOR_WARNING = "warning"
    COLOR_INFO = "info"
    COLOR_SUCCESS = "success"
    COLOR_SECONDARY = "secondary"
    COLORS = [
        (COLOR_PRIMARY, "Синий"),
        (COLOR_WARNING, "Жёлтый"),
        (COLOR_INFO, "Голубой"),
        (COLOR_SUCCESS, "Зелёный"),
        (COLOR_SECONDARY, "Серый"),
    ]
    COLOR_VALUES = [value for value, _ in COLORS]

    TEMPLATES = {
        "quick": {
            "title": "Быстрые услуги",
            "description": "Маникюр, стрижка, шиномонтаж, диагностика — короткий цикл.",
            "stages": [
                {"name": "Новая заявка", "color": COLOR_PRIMARY, "is_final": False},
                {"name": "Подтверждено", "color": COLOR_INFO, "is_final": False},
                {"name": "В работе", "color": COLOR_WARNING, "is_final": False},
                {"name": "Выполнено", "color": COLOR_SUCCESS, "is_final": True},
            ],
        },
        "complex": {
            "title": "Сложные заказы / Изготовление",
            "description": "Замер, предоплата, производство и сдача под ключ.",
            "stages": [
                {"name": "Новая заявка", "color": COLOR_PRIMARY, "is_final": False},
                {"name": "Замер / Осмотр", "color": COLOR_INFO, "is_final": False},
                {"name": "Предоплата", "color": COLOR_WARNING, "is_final": False},
                {
                    "name": "В работе / Изготовление",
                    "color": COLOR_SECONDARY,
                    "is_final": False,
                },
                {"name": "Выполнено", "color": COLOR_SUCCESS, "is_final": True},
            ],
        },
    }

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мастер",
        on_delete=models.CASCADE,
        related_name="pipeline_stages",
    )
    name = models.CharField("Название этапа", max_length=80)
    order = models.PositiveIntegerField("Порядок", default=0)
    color = models.CharField(
        "Цвет", max_length=16, choices=COLORS, default=COLOR_PRIMARY
    )
    is_final = models.BooleanField(
        "Финальный этап", default=False, help_text="Этап успешного завершения заказа."
    )

    class Meta:
        verbose_name = "Этап воронки"
        verbose_name_plural = "Этапы воронки"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_stage_name_per_owner"
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def badge_class(self) -> str:
        return f"text-bg-{self.color}"

    @property
    def is_first(self) -> bool:
        return not PipelineStage.objects.filter(
            owner_id=self.owner_id, order__lt=self.order
        ).exists()

    @classmethod
    def seed_defaults(cls, owner, template: str = "quick"):
        """Базовые этапы для нового мастера."""
        return cls.apply_template(owner, template)

    @classmethod
    def apply_template(cls, owner, template_key: str, replace: bool = False) -> int:
        """Приводит воронку к шаблону, добавляя недостающие этапы.

        replace=True пересобирает воронку с нуля, но только пока у мастера
        нет заказов — историю нельзя потерять. Существующие этапы с теми же
        названиями сохраняются и встают на свои места, а пользовательские
        этапы-дополнения уходят в конец.
        """
        template = cls.TEMPLATES.get(template_key)
        if template is None:
            raise ValueError(f"Неизвестный шаблон воронки: {template_key}")

        if replace and not Order.objects.filter(owner=owner).exists():
            cls.objects.filter(owner=owner).delete()

        existing = list(cls.objects.filter(owner=owner))
        by_name = {stage.name.strip().casefold(): stage for stage in existing}
        template_names = set()
        created = 0

        for index, item in enumerate(template["stages"], start=1):
            key = item["name"].strip().casefold()
            template_names.add(key)
            stage = by_name.get(key)
            if stage is None:
                cls.objects.create(
                    owner=owner,
                    name=item["name"],
                    order=index,
                    color=item["color"],
                    is_final=item["is_final"],
                )
                created += 1
                continue

            updates = []
            if stage.order != index:
                stage.order = index
                updates.append("order")
            if stage.color != item["color"]:
                stage.color = item["color"]
                updates.append("color")
            if stage.is_final != item["is_final"]:
                stage.is_final = item["is_final"]
                updates.append("is_final")
            if updates:
                stage.save(update_fields=updates)

        next_order = len(template["stages"]) + 1
        extras = [
            stage
            for stage in existing
            if stage.name.strip().casefold() not in template_names
        ]
        for stage in sorted(extras, key=lambda item: (item.order, item.pk)):
            # Этапы без заказов при загрузке шаблона убираем, а этапы с историей
            # сохраняем и переносим в конец, чтобы ничего не потерять.
            if not stage.orders.exists():
                stage.delete()
                continue
            if stage.order < next_order:
                stage.order = next_order
                stage.save(update_fields=["order"])
            next_order = max(next_order, stage.order) + 1

        return created


class Service(models.Model):
    """Услуга мастера с ценой, себестоимостью и длительностью."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мастер",
        on_delete=models.CASCADE,
        related_name="services",
    )
    name = models.CharField("Название услуги", max_length=160)
    price = models.DecimalField(
        "Цена", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    cost_price = models.DecimalField(
        "Себестоимость",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Расходники и материалы — вычитаются из прибыли.",
    )
    duration_minutes = models.PositiveIntegerField("Длительность, мин", default=60)
    is_active = models.BooleanField(
        "Показывать на публичной странице", default=True
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_service_name_per_owner"
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def margin(self) -> Decimal:
        return self.price - self.cost_price

    @property
    def margin_percent(self) -> Decimal:
        if self.price <= 0:
            return Decimal("0.00")
        return (self.margin / self.price * 100).quantize(Decimal("0.1"))

    @property
    def duration_label(self) -> str:
        hours, minutes = divmod(self.duration_minutes, 60)
        if hours and minutes:
            return f"{hours} ч {minutes} мин"
        if hours:
            return f"{hours} ч"
        return f"{minutes} мин"


class Order(models.Model):
    """Запись клиента: сделка, визит или заказ на изготовление."""

    PAYMENT_CASH = "cash"
    PAYMENT_CARD = "card"
    PAYMENT_NONE = "none"
    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Наличные"),
        (PAYMENT_CARD, "Карта"),
        (PAYMENT_NONE, "Без оплаты"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мастер",
        on_delete=models.CASCADE,
        related_name="orders",
    )
    client = models.ForeignKey(
        "core.Client",
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name="orders",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="Услуга",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    service_name = models.CharField("Услуга (снимок)", max_length=160, blank=True)
    stage = models.ForeignKey(
        PipelineStage,
        verbose_name="Этап",
        on_delete=models.RESTRICT,
        related_name="orders",
    )
    scheduled_at = models.DateTimeField("Дата и время визита")
    total_amount = models.DecimalField(
        "Итого", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    paid_amount = models.DecimalField(
        "Оплачено", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    payment_method = models.CharField(
        "Способ оплаты",
        max_length=8,
        choices=PAYMENT_CHOICES,
        default=PAYMENT_NONE,
    )
    work_details = models.TextField(
        "Работы и материалы",
        blank=True,
        help_text="История работ: марка масла, запчасти, формула краски и т.д.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["scheduled_at", "id"]
        indexes = [
            models.Index(fields=["owner", "stage"]),
            models.Index(fields=["owner", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.client.name} · {self.service_name or 'Без услуги'}"

    def save(self, *args, **kwargs):
        if self.service_id and not (self.service_name or "").strip():
            self.service_name = (
                Service.objects.filter(pk=self.service_id)
                .values_list("name", flat=True)
                .first()
                or ""
            )
        super().save(*args, **kwargs)

    @property
    def debt_amount(self) -> Decimal:
        return max(self.total_amount - self.paid_amount, Decimal("0.00"))

    @property
    def is_paid(self) -> bool:
        return self.debt_amount <= 0

    @property
    def is_overdue(self) -> bool:
        return self.debt_amount > 0 and self.scheduled_at < timezone.now()

    @property
    def cost_amount(self) -> Decimal:
        return self.service.cost_price if self.service_id else Decimal("0.00")

    @property
    def profit_amount(self) -> Decimal:
        return self.paid_amount - self.cost_amount

    @property
    def payment_label(self) -> str:
        return self.get_payment_method_display()

    def next_stage(self):
        """Следующий этап воронки этого мастера или None."""
        stages = list(
            PipelineStage.objects.filter(owner_id=self.owner_id).order_by("order", "id")
        )
        for index, stage in enumerate(stages):
            if stage.pk == self.stage_id:
                return stages[index + 1] if index + 1 < len(stages) else None
        return None

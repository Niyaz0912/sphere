"""Этапы воронки, услуги и заказы Сфера."""

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError


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
    old_price = models.DecimalField(
        "Старая цена",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Если указать цену выше текущей, на публичной странице появится скидка.",
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
    def discount_percent(self) -> int:
        """Целый процент скидки: старая цена выше текущей."""
        if self.old_price is None or self.old_price <= self.price:
            return 0
        if self.old_price <= 0:
            return 0
        discount = (self.old_price - self.price) / self.old_price * 100
        return int(discount.quantize(Decimal("1")))

    @property
    def has_discount(self) -> bool:
        return self.old_price is not None and self.old_price > self.price

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


class ServicePhoto(models.Model):
    """Фотография примера работы, привязанная к услуге мастера."""

    MAX_PHOTOS = 6
    MAX_SOURCE_SIZE = 10 * 1024 * 1024
    MAX_SIDE = 1200
    WEBP_QUALITY = 82
    ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

    service = models.ForeignKey(
        Service,
        verbose_name="Услуга",
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField("Фотография", upload_to="services/%Y/%m/")
    caption = models.CharField("Подпись к фото", max_length=120, blank=True)
    order = models.PositiveIntegerField("Порядок", default=0)
    created_at = models.DateTimeField("Загружена", auto_now_add=True)

    class Meta:
        verbose_name = "Фотография услуги"
        verbose_name_plural = "Фотографии услуг"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["service", "order"])]

    def __str__(self) -> str:
        return self.caption or f"Фото услуги «{self.service.name}»"

    @classmethod
    def validate_source_image(cls, upload):
        """Проверяет исходный файл: размер и реальный формат изображения."""
        if upload is None:
            raise ValidationError("Выберите файл изображения.")
        if getattr(upload, "size", 0) > cls.MAX_SOURCE_SIZE:
            limit_mb = cls.MAX_SOURCE_SIZE // (1024 * 1024)
            raise ValidationError(f"Файл больше {limit_mb} МБ.")

        try:
            with Image.open(upload) as image:
                image_format = (image.format or "").upper()
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise ValidationError("Не удалось прочитать изображение.") from error
        finally:
            try:
                upload.seek(0)
            except (AttributeError, OSError):
                pass

        if image_format not in cls.ALLOWED_FORMATS:
            raise ValidationError("Поддерживаются только JPG, PNG и WebP.")
        return image_format

    def _check_photo_limit(self) -> None:
        if not self.service_id:
            return
        siblings = ServicePhoto.objects.filter(service_id=self.service_id)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        if siblings.count() >= self.MAX_PHOTOS:
            raise ValidationError(
                f"К услуге можно добавить не более {self.MAX_PHOTOS} фотографий."
            )

    def _convert_to_webp(self) -> None:
        """Поворачивает по EXIF, уменьшает до 1200 px и сохраняет в WebP."""
        source = self.image
        self.validate_source_image(source)

        try:
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original)
                image.load()

                if image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                ):
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, (255, 255, 255))
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")

                image.thumbnail(
                    (self.MAX_SIDE, self.MAX_SIDE),
                    getattr(Image, "Resampling", Image).LANCZOS,
                )
                buffer = BytesIO()
                image.save(
                    buffer,
                    format="WEBP",
                    quality=self.WEBP_QUALITY,
                    method=6,
                )
        except ValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise ValidationError(
                "Не удалось обработать изображение."
            ) from error

        original_name = Path(getattr(source, "name", "") or "photo").stem[:80]
        self.image = ContentFile(
            buffer.getvalue(), name=f"{original_name or 'photo'}.webp"
        )

    def save(self, *args, **kwargs):
        self._check_photo_limit()
        if self.image and not getattr(self.image, "_committed", False):
            self._convert_to_webp()
        super().save(*args, **kwargs)


class PromoOffer(models.Model):
    """Акция мастера или нативное партнёрское предложение.

    Показывается на публичной странице, пока включена и не истекла дата.
    Переходы по ссылке партнёра считаются в clicks_count.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мастер",
        on_delete=models.CASCADE,
        related_name="promo_offers",
    )
    title = models.CharField("Заголовок акции", max_length=120)
    description = models.TextField("Описание предложения", blank=True)
    badge_text = models.CharField(
        "Текст бейджа", max_length=32, default="Акция"
    )
    promo_code = models.CharField("Промокод", max_length=40, blank=True)
    target_url = models.URLField("Ссылка партнёра", blank=True)
    is_featured = models.BooleanField(
        "Закрепить под шапкой",
        default=False,
        help_text="Главная акция месяца — показывается отдельной карточкой.",
    )
    expires_at = models.DateField("Действует до", null=True, blank=True)
    clicks_count = models.PositiveIntegerField("Переходов", default=0)
    is_active = models.BooleanField("Активна", default=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Акция"
        verbose_name_plural = "Акции"
        ordering = ["-is_featured", "-created_at", "-id"]
        indexes = [models.Index(fields=["owner", "is_active"])]

    def __str__(self) -> str:
        return self.title

    @property
    def is_expired(self) -> bool:
        return bool(
            self.expires_at and self.expires_at < timezone.localdate()
        )

    @property
    def is_live(self) -> bool:
        return self.is_active and not self.is_expired

    @property
    def status_label(self) -> str:
        if self.is_expired:
            return "Истекла"
        if self.is_active:
            return "Активна"
        return "Выключена"

    @property
    def status_class(self) -> str:
        return "status-pill--on" if self.is_live else "status-pill--off"

    @property
    def has_action(self) -> bool:
        return bool(self.promo_code or self.target_url)


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

"""Профиль мастера и клиентская база Сфера."""

import re
from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

SLUG_VALIDATOR = RegexValidator(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    "Используйте латиницу: строчные буквы, цифры и дефис (без пробелов).",
)

PHONE_RE = re.compile(r"[^\d+]")


def phone_digits(phone: str) -> str:
    """Только цифры номера — для сравнения записей «+7 999…» и «8999…»."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def phones_match(first: str, second: str) -> bool:
    """Сравнивает телефоны по последним 10 цифрам."""
    left, right = phone_digits(first), phone_digits(second)
    if not left or not right:
        return False
    if left == right:
        return True
    return len(left) >= 10 and len(right) >= 10 and left[-10:] == right[-10:]


def unique_slug_for(username: str, *, base: str | None = None, exclude_pk=None) -> str:
    """Свободный адрес публичной страницы: demo-service, demo-service-2, …"""
    candidate = (
        slugify(base or username or "master").replace("_", "-").strip("-")[:70]
        or "master"
    )
    queryset = MasterProfile.objects.all()
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    slug = candidate
    suffix = 2
    while queryset.filter(slug=slug).exists():
        slug = f"{candidate}-{suffix}"
        suffix += 1
    return slug


class MasterProfile(models.Model):
    """Публичная страница и настройки мастера. Один профиль на пользователя."""

    ORG_SELF = "self"
    ORG_IP = "ip"
    ORG_OOO = "ooo"
    ORG_STUDIO = "studio"
    ORG_TYPES = [
        (ORG_SELF, "Самозанятый / Частный мастер"),
        (ORG_IP, "Индивидуальный предприниматель (ИП)"),
        (ORG_OOO, "Организация (ООО)"),
        (ORG_STUDIO, "Студия / Сервис"),
    ]

    WORK_DAYS_CHOICES = [
        ("Пн–Пт", "Пн–Пт"),
        ("Пн–Сб", "Пн–Сб"),
        ("Вт–Вс", "Вт–Вс"),
        ("Без выходных (Ежедневно)", "Без выходных (Ежедневно)"),
        ("Пн–Пт (Сб, Вс — по договорённости)", "Пн–Пт (Сб, Вс — по договорённости)"),
        ("Пн–Сб (Вс — по предварительной записи)", "Пн–Сб (Вс — по предварительной записи)"),
        ("По предварительной записи", "По предварительной записи"),
    ]

    THEME_BLUE = "blue"
    THEME_DARK = "dark"
    THEME_ROSE = "rose"
    THEME_EMERALD = "emerald"
    THEMES = [
        (THEME_BLUE, "Синяя"),
        (THEME_DARK, "Тёмная"),
        (THEME_ROSE, "Розовая"),
        (THEME_EMERALD, "Изумрудная"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
        related_name="master_profile",
    )
    slug = models.SlugField(
        "Адрес страницы",
        max_length=80,
        unique=True,
        validators=[SLUG_VALIDATOR],
        help_text="Латиница, цифры и дефис. Публичная страница: /s/адрес/",
    )
    business_name = models.CharField("Название / Имя", max_length=120, blank=True)
    description = models.TextField(
        "Описание для клиентов",
        blank=True,
        help_text="Приветствие, специализация, чем вы отличаетесь.",
    )
    phone = models.CharField("Телефон", max_length=32, blank=True)
    telegram = models.CharField(
        "Telegram",
        max_length=64,
        blank=True,
        help_text="@username или ссылка на профиль.",
    )
    address = models.CharField("Адрес приёма", max_length=200, blank=True)
    theme = models.CharField(
        "Тема публичной страницы",
        max_length=16,
        choices=THEMES,
        default=THEME_BLUE,
    )
    org_type = models.CharField(
        "Форма деятельности",
        max_length=16,
        choices=ORG_TYPES,
        default=ORG_SELF,
    )
    work_days = models.CharField("Рабочие дни", max_length=64, choices=WORK_DAYS_CHOICES, default="Пн–Пт")
    work_hours = models.CharField("Часы работы", max_length=64, default="09:00 - 20:00")
    is_public = models.BooleanField(
        "Показывать на главной странице «Сферы»",
        default=True,
        help_text="Компания появится в витрине на главной странице площадки.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Профиль мастера"
        verbose_name_plural = "Профили мастеров"
        ordering = ["business_name", "slug"]

    def __str__(self) -> str:
        return self.display_name

    def save(self, *args, **kwargs):
        if self.slug:
            self.slug = (
                slugify(self.slug).replace("_", "-")[:80] or self.slug
            )
        if self.telegram:
            self.telegram = self.telegram.strip()
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("public_master", kwargs={"slug": self.slug})

    @property
    def display_name(self) -> str:
        return self.business_name.strip() or self.user.get_username()

    @property
    def initials(self) -> str:
        words = [word for word in self.display_name.replace("-", " ").split() if word]
        if not words:
            return "МБ"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    @property
    def phone_href(self) -> str:
        cleaned = PHONE_RE.sub("", self.phone or "")
        return f"tel:{cleaned}" if cleaned else ""

    @property
    def telegram_url(self) -> str:
        value = (self.telegram or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        return f"https://t.me/{value.lstrip('@')}"

    @property
    def telegram_handle(self) -> str:
        value = (self.telegram or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value.rstrip("/").rsplit("/", 1)[-1]
        return value if value.startswith("@") else f"@{value}"

    def public_url(self) -> str:
        return self.get_absolute_url()

    @classmethod
    def for_user(cls, user) -> "MasterProfile":
        """Профиль текущего пользователя; создаёт его для старых аккаунтов."""
        try:
            return user.master_profile
        except MasterProfile.DoesNotExist:
            profile = cls.objects.create(
                user=user,
                slug=unique_slug_for(user.get_username()),
                business_name=user.get_username(),
            )
            from shop.models import PipelineStage  # локальный импорт: apps ещё грузятся

            PipelineStage.seed_defaults(user)
            return profile


class Client(models.Model):
    """Клиент конкретного мастера: полностью изолирован по owner."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мастер",
        on_delete=models.CASCADE,
        related_name="clients",
    )
    name = models.CharField("Имя / ФИО", max_length=120)
    phone = models.CharField("Телефон", max_length=32)
    identifier = models.CharField(
        "Объект",
        max_length=80,
        blank=True,
        help_text="Гос. номер или VIN авто, модель техники, особенности клиента.",
    )
    notes = models.TextField(
        "Постоянные заметки",
        blank=True,
        help_text="Всё, что важно помнить о клиенте: предпочтения, аллергии, договорённости.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "phone"],
                name="unique_client_phone_per_owner",
            )
        ]
        indexes = [models.Index(fields=["owner", "name"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"

    @property
    def initials(self) -> str:
        words = [word for word in self.name.replace("-", " ").split() if word]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    @property
    def short_name(self) -> str:
        words = [word for word in self.name.split() if word]
        return words[0] if words else self.name

    @classmethod
    def find_by_phone(cls, owner, phone: str):
        """Ищет клиента мастера по номеру с точностью до последних 10 цифр."""
        if not phone_digits(phone):
            return None
        for client in cls.objects.filter(owner=owner).only("id", "phone", "name"):
            if phones_match(client.phone, phone):
                return client
        return None

    def total_revenue(self) -> Decimal:
        from django.db.models import Sum

        total = self.orders.aggregate(total=Sum("paid_amount"))["total"]
        return total or Decimal("0.00")

    def last_visit(self):
        from django.db.models import Max

        return self.orders.aggregate(last=Max("scheduled_at"))["last"]

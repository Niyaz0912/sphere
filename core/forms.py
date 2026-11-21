"""Формы профиля, регистрации, клиентов и публичной записи."""

from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from django.utils.text import slugify

from shop.models import PipelineStage, Service

from .models import Client, MasterProfile, phone_digits, phones_match, unique_slug_for


class BootstrapFormMixin:
    """Проставляет классы Bootstrap всем полям формы."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.RadioSelect):
                css = "form-check-input"
            elif isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            existing = (widget.attrs.get("class") or "").split()
            if css not in existing:
                widget.attrs["class"] = " ".join([*existing, css]).strip()


class RegisterForm(BootstrapFormMixin, UserCreationForm):
    """Регистрация мастера: логин, пароль, название и шаблон воронки."""

    org_type = forms.ChoiceField(
        label="Форма работы",
        choices=MasterProfile.ORG_TYPES,
        initial=MasterProfile.ORG_SELF,
        required=False,
    )
    business_name = forms.CharField(
        label="Название или Имя / ИП",
        max_length=120,
        widget=forms.TextInput(
            attrs={"placeholder": "Например, Студия «Сфера»", "autocomplete": "organization"}
        ),
        help_text="Так вас увидят клиенты на публичной странице.",
    )
    funnel_template = forms.ChoiceField(
        label="С чего начнём",
        choices=[
            ("quick", "Быстрые услуги"),
            ("complex", "Сложные заказы / Изготовление"),
        ],
        initial="quick",
        widget=forms.RadioSelect,
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)
        labels = {"username": "Логин"}
        help_texts = {
            "username": "Латиница, цифры и @ . + - _. Логин нужен только для входа.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "master", "autocomplete": "username", "autofocus": True}
        )
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "Не меньше 8 символов", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Повторите пароль", "autocomplete": "new-password"}
        )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Этот логин уже занят.")
        return username

    def clean_business_name(self):
        business_name = (self.cleaned_data.get("business_name") or "").strip()
        if not business_name:
            raise forms.ValidationError("Укажите название компании.")
        return business_name

    def save(self, commit=True):
        user = super().save(commit=commit)
        if not commit:
            return user

        profile = MasterProfile.for_user(user)
        profile.org_type = self.cleaned_data.get("org_type") or MasterProfile.ORG_SELF
        profile.business_name = self.cleaned_data["business_name"].strip()
        profile.slug = unique_slug_for(
            user.get_username(), exclude_pk=profile.pk
        )
        profile.save()

        if self.cleaned_data.get("funnel_template") == "complex":
            PipelineStage.apply_template(user, "complex", replace=True)
        return user


class MasterProfileForm(BootstrapFormMixin, forms.ModelForm):
    """Настройки публичной страницы компании."""

    class Meta:
        model = MasterProfile
        fields = [
            "slug",
            "org_type",
            "business_name",
            "description",
            "phone",
            "telegram",
            "address",
            "theme",
            "work_days",
            "work_hours",
            "is_public",
        ]
        widgets = {
            "slug": forms.TextInput(attrs={"placeholder": "demo-service"}),
            "business_name": forms.TextInput(
                attrs={"placeholder": "Компания «Сфера»"}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Расскажите, чем занимаетесь: услуги, опыт, подход к работе."
                },
            ),
            "phone": forms.TextInput(attrs={"placeholder": "+7 (999) 123-45-67"}),
            "telegram": forms.TextInput(attrs={"placeholder": "@sfera"}),
            "address": forms.TextInput(
                attrs={"placeholder": "г. Москва, ул. Примерная, 10"}
            ),
            "work_days": forms.Select(),
            "work_hours": forms.TextInput(attrs={"placeholder": "09:00 - 20:00"}),
            "theme": forms.RadioSelect,
            "is_public": forms.CheckboxInput,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "org_type" in self.fields:
            self.fields["org_type"].required = False
        if "work_days" in self.fields:
            self.fields["work_days"].required = False

    def clean_slug(self):
        raw = (self.cleaned_data.get("slug") or "").strip()
        slug = slugify(raw)
        if not slug:
            raise forms.ValidationError(
                "Напишите адрес латиницей: например, demo-service."
            )
        queryset = MasterProfile.objects.filter(slug=slug).exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Этот адрес уже занят другим мастером.")
        return slug

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if phone and not 10 <= len(phone_digits(phone)) <= 15:
            raise forms.ValidationError("В телефоне должно быть от 10 до 15 цифр.")
        return phone

    def clean_telegram(self):
        value = (self.cleaned_data.get("telegram") or "").strip()
        if value and len(value) > 64:
            raise forms.ValidationError("Слишком длинный адрес Telegram.")
        return value

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()

    def clean_business_name(self):
        value = (self.cleaned_data.get("business_name") or "").strip()
        if not value:
            raise forms.ValidationError("Укажите название компании.")
        return value

    def clean_org_type(self):
        return self.cleaned_data.get("org_type") or MasterProfile.ORG_SELF

    def clean_work_days(self):
        return self.cleaned_data.get("work_days") or "Пн–Пт"

    def clean_work_hours(self):
        value = (self.cleaned_data.get("work_hours") or "").strip()
        return value or "09:00 - 20:00"


class ClientForm(BootstrapFormMixin, forms.ModelForm):
    """Клиент мастера: форма создания и редактирования."""

    class Meta:
        model = Client
        fields = ["name", "phone", "identifier", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Иван Петров"}),
            "phone": forms.TextInput(
                attrs={"type": "tel", "placeholder": "+7 (999) 123-45-67"}
            ),
            "identifier": forms.TextInput(
                attrs={"placeholder": "А123ВС 77 / VIN / модель техники"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Постоянные заметки: предпочтения, договорённости."
                },
            ),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner or getattr(kwargs.get("instance"), "owner", None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Укажите имя клиента.")
        return name

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not 10 <= len(phone_digits(phone)) <= 15:
            raise forms.ValidationError("В телефоне должно быть от 10 до 15 цифр.")
        if self.owner is not None:
            others = Client.objects.filter(owner=self.owner)
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            for client in others.only("id", "phone", "name"):
                if phones_match(client.phone, phone):
                    raise forms.ValidationError(
                        f"Клиент с таким телефоном уже есть: {client.name}."
                    )
        return phone

    def clean_identifier(self):
        return (self.cleaned_data.get("identifier") or "").strip()


class PublicBookingForm(BootstrapFormMixin, forms.Form):
    """Единая форма записи клиента с публичной страницы компании."""

    service = forms.ModelChoiceField(
        label="Услуга",
        queryset=Service.objects.none(),
        empty_label="Выберите услугу",
    )
    name = forms.CharField(
        label="Имя и фамилия",
        max_length=120,
        widget=forms.TextInput(
            attrs={"placeholder": "Иван Петров", "autocomplete": "name"}
        ),
    )
    phone = forms.CharField(
        label="Телефон",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "placeholder": "+7 (999) 123-45-67",
                "autocomplete": "tel",
            }
        ),
    )
    scheduled_at = forms.DateTimeField(
        label="Дата и время",
        input_formats=[
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
        ),
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = (
            services if services is not None else Service.objects.none()
        )
        now = timezone.localtime()
        self.fields["scheduled_at"].widget.attrs.update(
            {
                "min": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
                "max": (now + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M"),
            }
        )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Как к вам обращаться?")
        return name

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not 10 <= len(phone_digits(phone)) <= 15:
            raise forms.ValidationError("Проверьте номер телефона.")
        return phone

    def clean_scheduled_at(self):
        scheduled = self.cleaned_data.get("scheduled_at")
        if scheduled is None:
            return scheduled
        now = timezone.localtime()
        if scheduled <= now:
            raise forms.ValidationError("Выберите будущие дату и время.")
        if scheduled > now + timedelta(days=180):
            raise forms.ValidationError(
                "Запись открыта не более чем на 180 дней вперёд."
            )
        return scheduled


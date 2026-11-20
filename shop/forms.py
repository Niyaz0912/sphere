"""Формы услуг, заказов и приёма оплаты."""

from decimal import Decimal

from django import forms

from core.forms import BootstrapFormMixin

from .models import Order, PipelineStage, Service


class ServiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "price", "cost_price", "duration_minutes", "is_active"]
        labels = {
            "name": "Название",
            "price": "Цена, ₽",
            "cost_price": "Себестоимость, ₽",
            "duration_minutes": "Длительность, мин",
            "is_active": "Показывать на публичной странице",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "Например, Замена масла и фильтров"}
            ),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "cost_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "duration_minutes": forms.NumberInput(attrs={"step": "5", "min": "1"}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner or getattr(kwargs.get("instance"), "owner", None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Введите название услуги.")
        if self.owner is not None:
            others = Service.objects.filter(owner=self.owner)
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            needle = name.casefold()
            for service in others.only("id", "name"):
                if service.name.strip().casefold() == needle:
                    raise forms.ValidationError("Услуга с таким названием уже есть.")
        return name

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None or price < 0:
            raise forms.ValidationError("Цена не может быть отрицательной.")
        return price

    def clean_cost_price(self):
        cost = self.cleaned_data.get("cost_price")
        if cost is None or cost < 0:
            raise forms.ValidationError("Себестоимость не может быть отрицательной.")
        return cost

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get("duration_minutes")
        if duration is None or duration < 1:
            raise forms.ValidationError("Длительность должна быть хотя бы 1 минута.")
        if duration > 1440:
            raise forms.ValidationError("Длительность не может быть больше 24 часов.")
        return duration


class OrderForm(BootstrapFormMixin, forms.ModelForm):
    """Создание и редактирование записи мастера."""

    class Meta:
        model = Order
        fields = [
            "client",
            "service",
            "stage",
            "scheduled_at",
            "total_amount",
            "paid_amount",
            "payment_method",
            "work_details",
        ]
        labels = {
            "client": "Клиент",
            "service": "Услуга из прайса",
            "stage": "Этап",
            "scheduled_at": "Дата и время",
            "total_amount": "Сумма заказа, ₽",
            "paid_amount": "Оплачено, ₽",
            "payment_method": "Способ оплаты",
            "work_details": "Работы и материалы",
        }
        widgets = {
            "scheduled_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            ),
            "total_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "paid_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "work_details": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Марка масла, запчасти, формула краски, договорённости…"
                },
            ),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner or getattr(kwargs.get("instance"), "owner", None)
        super().__init__(*args, **kwargs)

        if self.owner is not None:
            self.fields["client"].queryset = self.owner.clients.order_by("name")
            self.fields["service"].queryset = self.owner.services.order_by("name")
            self.fields["stage"].queryset = self.owner.pipeline_stages.order_by(
                "order", "id"
            )

        self.fields["service"].required = False
        self.fields["service"].empty_label = "Без услуги"
        self.fields["scheduled_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ]
        self.fields["payment_method"].required = False

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get("total_amount")
        paid = cleaned.get("paid_amount")
        if total is not None and paid is not None and paid > total:
            self.add_error(
                "paid_amount", "Оплата не может быть больше суммы заказа."
            )
        if total is not None and total < 0:
            self.add_error("total_amount", "Сумма не может быть отрицательной.")
        if paid is not None and paid < 0:
            self.add_error("paid_amount", "Оплата не может быть отрицательной.")
        return cleaned

    def save(self, commit=True):
        order = super().save(commit=False)
        if order.service_id:
            order.service_name = order.service.name
        elif "service" in self.changed_data:
            order.service_name = ""
        if commit:
            order.save()
            self.save_m2m()
        return order


class PaymentForm(BootstrapFormMixin, forms.Form):
    """Быстрый приём оплаты по заказу."""

    amount = forms.DecimalField(
        label="Сумма к оплате, ₽",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )
    payment_method = forms.ChoiceField(
        label="Способ оплаты",
        choices=[
            (Order.PAYMENT_CASH, "Наличные"),
            (Order.PAYMENT_CARD, "Карта"),
        ],
        initial=Order.PAYMENT_CASH,
        widget=forms.RadioSelect,
    )

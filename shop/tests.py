"""Тесты воронки, заказов, услуг, аналитики, Excel и демо-данных."""

import shutil
import tempfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from PIL import Image

from core.models import Client, MasterProfile

from .analytics import build_analytics
from .assistant import build_suggestions
from .excel import HEADERS, export_workbook, template_workbook
from .models import (
    Order,
    PipelineStage,
    PromoOffer,
    Service,
    ServicePhoto,
)

User = get_user_model()


def uploaded_image(
    name="photo.jpg",
    size=(1600, 900),
    image_format="JPEG",
    color=(37, 99, 235),
):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    content_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }.get(image_format, "application/octet-stream")
    return SimpleUploadedFile(
        name, buffer.getvalue(), content_type=content_type
    )


class MediaTestCase(TestCase):
    """Общий временный MEDIA_ROOT, чтобы тесты не писали фото в проект."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = settings.BASE_DIR / "test-media-shop"
        shutil.rmtree(cls._media_dir, ignore_errors=True)
        cls._media_dir.mkdir(parents=True, exist_ok=True)
        cls._media_override = override_settings(MEDIA_ROOT=str(cls._media_dir))
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)


def local_at(days: int = 0, hour: int = 12, minute: int = 0):
    base = timezone.localtime() + timedelta(days=days)
    naive = datetime.combine(base.date(), time(hour, minute))
    return timezone.make_aware(naive, timezone.get_current_timezone())


class ShopBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("master", password="StrongPass123")
        cls.stages = list(
            PipelineStage.objects.filter(owner=cls.user).order_by("order", "id")
        )
        cls.service = Service.objects.create(
            owner=cls.user,
            name="Компьютерная диагностика",
            price=Decimal("2000.00"),
            cost_price=Decimal("500.00"),
            duration_minutes=90,
        )
        cls.client_obj = Client.objects.create(
            owner=cls.user,
            name="Иван Петров",
            phone="+7 999 123-45-67",
            identifier="А123ВС 77",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def make_order(self, **overrides):
        data = {
            "owner": self.user,
            "client": self.client_obj,
            "service": self.service,
            "service_name": self.service.name,
            "stage": self.stages[0],
            "scheduled_at": local_at(0),
            "total_amount": Decimal("2000.00"),
            "paid_amount": Decimal("0.00"),
            "payment_method": Order.PAYMENT_NONE,
            "work_details": "",
        }
        data.update(overrides)
        return Order.objects.create(**data)


class PipelineStageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("master", password="StrongPass123")

    def test_apply_template_merges_missing_stages(self):
        added = PipelineStage.apply_template(self.user, "complex")
        self.assertEqual(added, 3)
        names = set(
            PipelineStage.objects.filter(owner=self.user).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(len(names), 5)
        self.assertIn("Предоплата", names)
        stages = list(
            PipelineStage.objects.filter(owner=self.user).order_by("order", "id")
        )
        self.assertEqual(stages[-1].name, "Выполнено")

    def test_replace_template_without_orders(self):
        PipelineStage.apply_template(self.user, "complex", replace=True)
        stages = list(
            PipelineStage.objects.filter(owner=self.user).order_by("order", "id")
        )
        self.assertEqual(len(stages), 5)
        self.assertEqual(stages[-1].name, "Выполнено")
        self.assertTrue(stages[-1].is_final)

    def test_replace_template_keeps_stages_with_orders(self):
        stage = PipelineStage.objects.filter(owner=self.user).first()
        client = Client.objects.create(
            owner=self.user, name="Клиент", phone="+7 999 111-22-33"
        )
        Order.objects.create(
            owner=self.user,
            client=client,
            stage=stage,
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        PipelineStage.apply_template(self.user, "complex", replace=True)
        self.assertTrue(Order.objects.filter(owner=self.user).exists())
        self.assertTrue(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            PipelineStage.apply_template(self.user, "unknown")


class ServiceModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("master", password="StrongPass123")

    def test_margin_and_duration(self):
        service = Service.objects.create(
            owner=self.user,
            name="Кухня",
            price=Decimal("100000.00"),
            cost_price=Decimal("40000.00"),
            duration_minutes=150,
        )
        self.assertEqual(service.margin, Decimal("60000.00"))
        self.assertEqual(service.margin_percent, Decimal("60.0"))
        self.assertEqual(service.duration_label, "2 ч 30 мин")

    def test_zero_price_margin(self):
        service = Service(price=Decimal("0.00"), cost_price=Decimal("0.00"))
        self.assertEqual(service.margin_percent, Decimal("0.00"))
        self.assertEqual(service.duration_label, "1 ч")

    def test_discount_percent_from_old_price(self):
        service = Service(
            price=Decimal("800.00"), old_price=Decimal("1000.00")
        )
        self.assertTrue(service.has_discount)
        self.assertEqual(service.discount_percent, 20)

    def test_no_discount_without_or_lower_old_price(self):
        service = Service(price=Decimal("1000.00"))
        self.assertFalse(service.has_discount)
        self.assertEqual(service.discount_percent, 0)

        service.old_price = Decimal("900.00")
        self.assertFalse(service.has_discount)
        self.assertEqual(service.discount_percent, 0)


class PromoOfferModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("promo-master", password="StrongPass123")

    def test_defaults_and_status(self):
        promo = PromoOffer.objects.create(owner=self.user, title="Скидка 20%")
        self.assertEqual(promo.badge_text, "Акция")
        self.assertEqual(promo.clicks_count, 0)
        self.assertTrue(promo.is_active)
        self.assertFalse(promo.is_expired)
        self.assertTrue(promo.is_live)
        self.assertEqual(promo.status_label, "Активна")
        self.assertEqual(str(promo), "Скидка 20%")

    def test_expired_promo_is_not_live(self):
        promo = PromoOffer.objects.create(
            owner=self.user,
            title="Старая акция",
            expires_at=timezone.localdate() - timedelta(days=1),
        )
        self.assertTrue(promo.is_expired)
        self.assertFalse(promo.is_live)
        self.assertEqual(promo.status_label, "Истекла")

    def test_disabled_promo_is_not_live(self):
        promo = PromoOffer.objects.create(
            owner=self.user,
            title="Выключенная акция",
            is_active=False,
        )
        self.assertFalse(promo.is_expired)
        self.assertFalse(promo.is_live)
        self.assertEqual(promo.status_label, "Выключена")

    def test_promo_expires_today_is_still_live(self):
        promo = PromoOffer.objects.create(
            owner=self.user,
            title="Последний день",
            expires_at=timezone.localdate(),
        )
        self.assertFalse(promo.is_expired)
        self.assertTrue(promo.is_live)


class OrderModelTests(ShopBase):
    def test_snapshot_debt_and_next_stage(self):
        order = self.make_order(
            service_name="",
            total_amount=Decimal("3000.00"),
            paid_amount=Decimal("1000.00"),
        )
        order.refresh_from_db()
        self.assertEqual(order.service_name, "Компьютерная диагностика")
        self.assertEqual(order.debt_amount, Decimal("2000.00"))
        self.assertFalse(order.is_paid)
        self.assertEqual(order.next_stage(), self.stages[1])

    def test_final_stage_has_no_next(self):
        order = self.make_order(stage=self.stages[-1])
        self.assertIsNone(order.next_stage())

    def test_cost_and_profit(self):
        order = self.make_order(
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("2000.00"),
        )
        self.assertEqual(order.cost_amount, Decimal("500.00"))
        self.assertEqual(order.profit_amount, Decimal("1500.00"))

    def test_order_without_service_has_zero_cost(self):
        order = self.make_order(service=None, service_name="Ручная работа")
        self.assertEqual(order.cost_amount, Decimal("0.00"))


class DashboardTests(ShopBase):
    def test_dashboard_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("shop:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_kanban_columns_and_own_orders_only(self):
        self.make_order(scheduled_at=local_at(0, 10))

        other = User.objects.create_user("other", password="StrongPass123")
        other_client = Client.objects.create(
            owner=other, name="Чужой Клиент", phone="+7 900 000-00-09"
        )
        Order.objects.create(
            owner=other,
            client=other_client,
            stage=PipelineStage.objects.filter(owner=other).first(),
            scheduled_at=local_at(0),
            total_amount=Decimal("999.00"),
        )

        response = self.client.get(reverse("shop:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columns"]), len(self.stages))
        self.assertEqual(response.context["view_mode"], "kanban")
        self.assertContains(response, "Иван Петров")
        self.assertNotContains(response, "Чужой Клиент")
        self.assertContains(response, "Умный помощник")

    def test_list_filters(self):
        today = self.make_order(scheduled_at=local_at(0, 10))
        tomorrow = self.make_order(scheduled_at=local_at(1, 10))
        old = self.make_order(scheduled_at=local_at(-5, 10))
        done = self.make_order(
            scheduled_at=local_at(0, 9),
            stage=self.stages[-1],
            paid_amount=Decimal("2000.00"),
        )

        url = reverse("shop:dashboard")
        cases = {
            "today": {today.pk, done.pk},
            "tomorrow": {tomorrow.pk},
            "active": {today.pk, tomorrow.pk, old.pk},
            "done": {done.pk},
        }
        for filter_key, expected in cases.items():
            response = self.client.get(url, {"view": "list", "filter": filter_key})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["view_mode"], "list")
            actual = {order.pk for order in response.context["orders"]}
            self.assertEqual(actual, expected, filter_key)

    def test_invalid_view_and_filter_fall_back(self):
        response = self.client.get(
            reverse("shop:dashboard"), {"view": "hacked", "filter": "hacked"}
        )
        self.assertEqual(response.context["view_mode"], "kanban")
        self.assertEqual(response.context["filter_key"], "active")

    def test_stats(self):
        self.make_order(
            scheduled_at=local_at(0, 10),
            total_amount=Decimal("3000.00"),
            paid_amount=Decimal("1000.00"),
        )
        self.make_order(
            scheduled_at=local_at(3, 10),
            total_amount=Decimal("5000.00"),
            paid_amount=Decimal("0.00"),
        )
        response = self.client.get(reverse("shop:dashboard"))
        stats = response.context["stats"]
        self.assertEqual(stats["active"], 2)
        self.assertEqual(stats["debt"], Decimal("7000.00"))
        self.assertEqual(stats["today"], 1)


class DashboardOnboardingTests(ShopBase):
    def test_dashboard_has_public_link_card(self):
        response = self.client.get(reverse("shop:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/s/master/")
        self.assertContains(response, "Скопировать ссылку")
        self.assertContains(response, "Открыть страницу глазами клиента")
        self.assertContains(response, "Создать запись")

    def test_dashboard_without_services_shows_onboarding_button(self):
        self.service.delete()
        response = self.client.get(reverse("shop:dashboard"))
        self.assertContains(response, "Сначала добавьте услуги")
        self.assertNotContains(response, "Создать запись")

    def test_services_page_has_public_link_card(self):
        response = self.client.get(reverse("shop:services"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Скопировать ссылку")
        self.assertContains(response, "Открыть страницу глазами клиента")
        self.assertContains(response, "/s/master/")

    def test_services_page_onboarding_banner(self):
        self.service.delete()
        response = self.client.get(
            f"{reverse('shop:services')}?onboarding=1"
        )
        self.assertContains(
            response,
            "Шаг 1: Создайте хотя бы одну услугу, чтобы клиенты могли "
            "записываться на вашу страницу",
        )

    def test_dashboard_is_not_root(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        dashboard = self.client.get("/")
        self.assertRedirects(dashboard, reverse("shop:dashboard"))


class AssistantTests(ShopBase):
    def test_no_suggestions_for_empty_account(self):
        self.assertEqual(build_suggestions(self.user), [])

    def test_debt_on_final_stage(self):
        self.make_order(
            stage=self.stages[-1],
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("400.00"),
        )
        suggestions = build_suggestions(self.user)
        self.assertEqual([item["kind"] for item in suggestions], ["debt"])
        self.assertIn("600 ₽", suggestions[0]["text"])

    def test_stale_order(self):
        order = self.make_order(stage=self.stages[0])
        Order.objects.filter(pk=order.pk).update(
            updated_at=timezone.now() - timedelta(days=5)
        )
        suggestions = build_suggestions(self.user)
        self.assertEqual([item["kind"] for item in suggestions], ["stale"])
        self.assertIn("Иван Петров", suggestions[0]["text"])

    def test_sleeping_client(self):
        sleeping = Client.objects.create(
            owner=self.user, name="Спящий Клиент", phone="+7 900 111-22-33"
        )
        self.make_order(
            client=sleeping,
            scheduled_at=local_at(-100),
            stage=self.stages[-1],
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("2000.00"),
            payment_method=Order.PAYMENT_CASH,
        )
        profile = MasterProfile.objects.get(user=self.user)
        profile.business_name = "Мастерская «Тест»"
        profile.phone = "+7 999 000-00-00"
        profile.save()

        suggestions = build_suggestions(self.user, profile)
        self.assertEqual([item["kind"] for item in suggestions], ["sleeping"])
        self.assertEqual(len(suggestions[0]["items"]), 1)
        reminder = suggestions[0]["items"][0]["reminder"]
        self.assertIn("Спящий", reminder)
        self.assertIn("Мастерская «Тест»", reminder)

    def test_all_three_suggestions_and_limit(self):
        self.make_order(
            stage=self.stages[-1],
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("400.00"),
        )
        stale = self.make_order(stage=self.stages[0])
        Order.objects.filter(pk=stale.pk).update(
            updated_at=timezone.now() - timedelta(days=6)
        )
        sleeping = Client.objects.create(
            owner=self.user, name="Спящий", phone="+7 900 222-33-44"
        )
        old = self.make_order(client=sleeping, scheduled_at=local_at(-120))
        Order.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=120)
        )

        suggestions = build_suggestions(self.user)
        self.assertEqual(
            [item["kind"] for item in suggestions],
            ["debt", "stale", "sleeping"],
        )
        self.assertLessEqual(len(suggestions), 3)

    def test_recent_client_is_not_sleeping(self):
        self.make_order(scheduled_at=local_at(-5))
        self.assertEqual(build_suggestions(self.user), [])


class OrderCreateTests(ShopBase):
    def test_create_page_opens(self):
        response = self.client.get(reverse("shop:order_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Новая запись")
        self.assertContains(response, "Иван Петров")

    def test_create_order(self):
        response = self.client.post(
            reverse("shop:order_create"),
            {
                "client": self.client_obj.pk,
                "service": self.service.pk,
                "stage": self.stages[0].pk,
                "scheduled_at": local_at(1, 15).strftime("%Y-%m-%dT%H:%M"),
                "total_amount": "2500.00",
                "paid_amount": "500.00",
                "payment_method": "card",
                "work_details": "Проверить подвеску",
            },
        )
        self.assertRedirects(response, reverse("shop:dashboard"))
        order = Order.objects.get(owner=self.user)
        self.assertEqual(order.client, self.client_obj)
        self.assertEqual(order.service_name, "Компьютерная диагностика")
        self.assertEqual(order.stage, self.stages[0])
        self.assertEqual(order.total_amount, Decimal("2500.00"))
        self.assertEqual(order.paid_amount, Decimal("500.00"))
        self.assertEqual(order.payment_method, Order.PAYMENT_CARD)

    def test_paid_more_than_total_is_rejected(self):
        response = self.client.post(
            reverse("shop:order_create"),
            {
                "client": self.client_obj.pk,
                "stage": self.stages[0].pk,
                "scheduled_at": local_at(1).strftime("%Y-%m-%dT%H:%M"),
                "total_amount": "1000.00",
                "paid_amount": "2000.00",
                "payment_method": "cash",
                "work_details": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("paid_amount", response.context["form"].errors)
        self.assertFalse(Order.objects.filter(owner=self.user).exists())

    def test_foreign_client_is_rejected(self):
        other = User.objects.create_user("other", password="StrongPass123")
        foreign_client = Client.objects.create(
            owner=other, name="Чужой", phone="+7 900 333-44-55"
        )
        response = self.client.post(
            reverse("shop:order_create"),
            {
                "client": foreign_client.pk,
                "stage": self.stages[0].pk,
                "scheduled_at": local_at(1).strftime("%Y-%m-%dT%H:%M"),
                "total_amount": "1000.00",
                "paid_amount": "0.00",
                "payment_method": "none",
                "work_details": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("client", response.context["form"].errors)
        self.assertFalse(Order.objects.filter(owner=self.user).exists())


class OrderEditPayAdvanceTests(ShopBase):
    def setUp(self):
        super().setUp()
        self.order = self.make_order(
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("0.00"),
        )

    def edit_payload(self, **overrides):
        data = {
            "client": self.client_obj.pk,
            "service": self.service.pk,
            "stage": self.stages[1].pk,
            "scheduled_at": local_at(2, 16).strftime("%Y-%m-%dT%H:%M"),
            "total_amount": "2500.00",
            "paid_amount": "500.00",
            "payment_method": "card",
            "work_details": "Новые работы и материалы",
        }
        data.update(overrides)
        return data

    def test_order_edit_updates_fields(self):
        response = self.client.post(
            reverse("shop:order_edit", kwargs={"pk": self.order.pk}),
            self.edit_payload(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, self.stages[1])
        self.assertEqual(self.order.total_amount, Decimal("2500.00"))
        self.assertEqual(self.order.paid_amount, Decimal("500.00"))
        self.assertEqual(self.order.payment_method, Order.PAYMENT_CARD)
        self.assertEqual(self.order.work_details, "Новые работы и материалы")

    def test_order_edit_changes_service_snapshot(self):
        second = Service.objects.create(
            owner=self.user, name="Шиномонтаж", price=Decimal("4000.00")
        )
        response = self.client.post(
            reverse("shop:order_edit", kwargs={"pk": self.order.pk}),
            self.edit_payload(service=second.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.service, second)
        self.assertEqual(self.order.service_name, "Шиномонтаж")

    def test_order_edit_can_clear_service(self):
        response = self.client.post(
            reverse("shop:order_edit", kwargs={"pk": self.order.pk}),
            self.edit_payload(service=""),
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.service)
        self.assertEqual(self.order.service_name, "")

    def test_order_edit_rejects_overpayment(self):
        response = self.client.post(
            reverse("shop:order_edit", kwargs={"pk": self.order.pk}),
            self.edit_payload(paid_amount="5000.00"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("paid_amount", response.json()["errors"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal("0.00"))

    def test_order_edit_foreign_order_is_404(self):
        other = User.objects.create_user("other", password="StrongPass123")
        other_client = Client.objects.create(
            owner=other, name="Чужой", phone="+7 900 555-66-77"
        )
        foreign = Order.objects.create(
            owner=other,
            client=other_client,
            stage=PipelineStage.objects.filter(owner=other).first(),
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        response = self.client.post(
            reverse("shop:order_edit", kwargs={"pk": foreign.pk}),
            self.edit_payload(),
        )
        self.assertEqual(response.status_code, 404)

    def test_pay_accepts_cash(self):
        response = self.client.post(
            reverse("shop:order_pay", kwargs={"pk": self.order.pk}),
            {"amount": "500.00", "payment_method": "cash"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["debt_amount"], "1500.00")
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal("500.00"))
        self.assertEqual(self.order.payment_method, Order.PAYMENT_CASH)

    def test_pay_accepts_card_and_closes_debt(self):
        self.client.post(
            reverse("shop:order_pay", kwargs={"pk": self.order.pk}),
            {"amount": "2000.00", "payment_method": "card"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal("2000.00"))
        self.assertEqual(self.order.debt_amount, Decimal("0.00"))
        self.assertEqual(self.order.payment_method, Order.PAYMENT_CARD)

    def test_pay_more_than_debt_is_rejected(self):
        response = self.client.post(
            reverse("shop:order_pay", kwargs={"pk": self.order.pk}),
            {"amount": "2500.00", "payment_method": "cash"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.json()["errors"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal("0.00"))

    def test_pay_already_paid_order_is_rejected(self):
        Order.objects.filter(pk=self.order.pk).update(
            paid_amount=Decimal("2000.00")
        )
        response = self.client.post(
            reverse("shop:order_pay", kwargs={"pk": self.order.pk}),
            {"amount": "100.00", "payment_method": "cash"},
        )
        self.assertEqual(response.status_code, 400)

    def test_pay_invalid_amount_is_rejected(self):
        response = self.client.post(
            reverse("shop:order_pay", kwargs={"pk": self.order.pk}),
            {"amount": "abc", "payment_method": "cash"},
        )
        self.assertEqual(response.status_code, 400)

    def test_pay_foreign_order_is_404(self):
        other = User.objects.create_user("other", password="StrongPass123")
        other_client = Client.objects.create(
            owner=other, name="Чужой", phone="+7 900 888-99-00"
        )
        foreign = Order.objects.create(
            owner=other,
            client=other_client,
            stage=PipelineStage.objects.filter(owner=other).first(),
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        response = self.client.post(
            reverse("shop:order_pay", kwargs={"pk": foreign.pk}),
            {"amount": "100.00", "payment_method": "cash"},
        )
        self.assertEqual(response.status_code, 404)

    def test_advance_moves_to_next_stage(self):
        response = self.client.post(
            reverse("shop:order_advance", kwargs={"pk": self.order.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stage"], self.stages[1].name)
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, self.stages[1])

    def test_advance_on_final_stage_is_rejected(self):
        order = self.make_order(stage=self.stages[-1])
        response = self.client.post(
            reverse("shop:order_advance", kwargs={"pk": order.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_advance_without_ajax_redirects(self):
        response = self.client.post(
            reverse("shop:order_advance", kwargs={"pk": self.order.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, self.stages[1])

    def test_advance_foreign_order_is_404(self):
        other = User.objects.create_user("other", password="StrongPass123")
        other_client = Client.objects.create(
            owner=other, name="Чужой", phone="+7 900 777-66-55"
        )
        foreign = Order.objects.create(
            owner=other,
            client=other_client,
            stage=PipelineStage.objects.filter(owner=other).first(),
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        response = self.client.post(
            reverse("shop:order_advance", kwargs={"pk": foreign.pk})
        )
        self.assertEqual(response.status_code, 404)


class ServiceViewTests(ShopBase):
    def test_list_shows_only_own_services(self):
        other = User.objects.create_user("other", password="StrongPass123")
        Service.objects.create(owner=other, name="Чужая услуга", price=Decimal("10"))
        response = self.client.get(reverse("shop:services"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Компьютерная диагностика")
        self.assertNotContains(response, "Чужая услуга")

    def test_create_service(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "name": "Полировка кузова",
                "price": "8000.00",
                "cost_price": "2200.00",
                "duration_minutes": "120",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        service = Service.objects.get(owner=self.user, name="Полировка кузова")
        self.assertEqual(service.price, Decimal("8000.00"))
        self.assertEqual(service.cost_price, Decimal("2200.00"))
        self.assertTrue(service.is_active)

    def test_duplicate_service_name_is_rejected_case_insensitively(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "name": "компьютерная диагностика",
                "price": "1000.00",
                "cost_price": "0.00",
                "duration_minutes": "60",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["errors"])

    def test_negative_price_is_rejected(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "name": "Минус",
                "price": "-10.00",
                "cost_price": "0.00",
                "duration_minutes": "60",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("price", response.json()["errors"])

    def test_edit_service(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "id": self.service.pk,
                "name": "Диагностика Pro",
                "price": "3000.00",
                "cost_price": "700.00",
                "duration_minutes": "120",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.name, "Диагностика Pro")
        self.assertEqual(self.service.price, Decimal("3000.00"))
        self.assertEqual(self.service.duration_minutes, 120)

    def test_edit_foreign_service_is_404(self):
        other = User.objects.create_user("other", password="StrongPass123")
        foreign = Service.objects.create(
            owner=other, name="Чужая", price=Decimal("100")
        )
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "id": foreign.pk,
                "name": "Взлом",
                "price": "1.00",
                "duration_minutes": "60",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_service_keeps_order_snapshot(self):
        order = self.make_order()
        response = self.client.post(
            reverse("shop:service_delete", kwargs={"pk": self.service.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Service.objects.filter(pk=self.service.pk).exists())
        order.refresh_from_db()
        self.assertIsNone(order.service)
        self.assertEqual(order.service_name, "Компьютерная диагностика")

    def test_delete_foreign_service_is_404(self):
        other = User.objects.create_user("other", password="StrongPass123")
        foreign = Service.objects.create(
            owner=other, name="Чужая", price=Decimal("100")
        )
        response = self.client.post(
            reverse("shop:service_delete", kwargs={"pk": foreign.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_service_export_workbook(self):
        response = self.client.get(reverse("shop:service_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet.cell(row=2, column=1).value, "Компьютерная диагностика")

    def test_template_workbook_has_only_headers(self):
        response = self.client.get(reverse("shop:service_template"))
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet.max_row, 1)

    def test_import_services(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(HEADERS)
        sheet.append(["Новая услуга", 3000, 500, 60, "да"])
        sheet.append(["Компьютерная диагностика", 2500, 500, 90, "нет"])
        sheet.append(["", 1000, 0, 30, "да"])
        sheet.append(["Плохая услуга", "не число", 0, 30, "да"])
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        upload = SimpleUploadedFile(
            "price.xlsx",
            stream.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("shop:service_import"), {"file": upload}
        )
        self.assertRedirects(
            response,
            reverse("shop:service_import"),
            fetch_redirect_response=False,
        )

        result = self.client.session["service_import_result"]
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["total"], 4)

        self.assertTrue(
            Service.objects.filter(owner=self.user, name="Новая услуга").exists()
        )
        self.service.refresh_from_db()
        self.assertEqual(self.service.price, Decimal("2500.00"))
        self.assertFalse(self.service.is_active)

        page = self.client.get(reverse("shop:service_import"))
        self.assertContains(page, "Результат импорта")
        self.assertContains(page, "Создано: 1")

    def test_import_rejects_wrong_extension(self):
        upload = SimpleUploadedFile("price.csv", b"name,price", content_type="text/csv")
        response = self.client.post(
            reverse("shop:service_import"), {"file": upload}, follow=True
        )
        self.assertContains(response, "только файлы .xlsx")
        self.assertEqual(Service.objects.filter(owner=self.user).count(), 1)

    def test_export_workbook_helper_contains_headers(self):
        workbook = load_workbook(export_workbook(self.user))
        self.assertEqual([cell.value for cell in workbook.active[1]], HEADERS)
        empty = load_workbook(template_workbook())
        self.assertEqual(empty.active.max_row, 1)


class ServiceOldPriceTests(ShopBase):
    def test_create_service_with_old_price(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "name": "Полировка с акцией",
                "price": "4000.00",
                "old_price": "5000.00",
                "cost_price": "1000.00",
                "duration_minutes": "120",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        service = Service.objects.get(owner=self.user, name="Полировка с акцией")
        self.assertEqual(service.old_price, Decimal("5000.00"))
        self.assertEqual(service.discount_percent, 20)

    def test_negative_old_price_is_rejected(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "name": "Минус старая цена",
                "price": "1000.00",
                "old_price": "-10.00",
                "cost_price": "0.00",
                "duration_minutes": "60",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("old_price", response.json()["errors"])
        self.assertFalse(
            Service.objects.filter(owner=self.user, name="Минус старая цена").exists()
        )

    def test_edit_service_sets_old_price(self):
        response = self.client.post(
            reverse("shop:service_save"),
            {
                "id": self.service.pk,
                "name": self.service.name,
                "price": "2000.00",
                "old_price": "2500.00",
                "cost_price": "500.00",
                "duration_minutes": "90",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.old_price, Decimal("2500.00"))
        self.assertEqual(self.service.discount_percent, 20)


class ServicePhotoTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "photo-master", password="StrongPass123"
        )
        cls.service = Service.objects.create(
            owner=cls.user, name="Полировка кузова", price=Decimal("5000.00")
        )
        cls.other = User.objects.create_user(
            "photo-other", password="StrongPass123"
        )
        cls.foreign_service = Service.objects.create(
            owner=cls.other, name="Чужая услуга", price=Decimal("1000.00")
        )

    def setUp(self):
        self.client.force_login(self.user)

    def make_photo(self, service=None, **kwargs):
        data = {
            "service": service or self.service,
            "image": uploaded_image(size=(800, 600)),
            "caption": "Пример работы",
        }
        data.update(kwargs)
        return ServicePhoto.objects.create(**data)

    def test_new_photo_is_converted_to_webp_and_resized(self):
        photo = ServicePhoto.objects.create(
            service=self.service,
            image=uploaded_image(size=(1600, 900)),
            caption="До / после",
        )
        self.assertTrue(photo.image.name.endswith(".webp"))
        path = Path(photo.image.path)
        self.assertTrue(path.exists())
        with Image.open(path) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (1200, 675))
            self.assertLessEqual(max(image.size), 1200)

    def test_upload_view_accepts_multiple_files(self):
        response = self.client.post(
            reverse(
                "shop:service_photo_upload",
                kwargs={"pk": self.service.pk},
            ),
            {
                "images": [
                    uploaded_image("one.jpg", size=(800, 600)),
                    uploaded_image(
                        "two.png", size=(640, 480), image_format="PNG"
                    ),
                ],
                "caption": "Пример работы",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["created"], 2)
        photos = list(self.service.photos.all())
        self.assertEqual(len(photos), 2)
        self.assertTrue(all(photo.image.name.endswith(".webp") for photo in photos))
        self.assertTrue(all(photo.caption == "Пример работы" for photo in photos))

    def test_six_photo_limit_is_enforced(self):
        for index in range(ServicePhoto.MAX_PHOTOS):
            self.make_photo(caption=f"Фото {index + 1}")

        with self.assertRaises(ValidationError):
            ServicePhoto.objects.create(
                service=self.service,
                image=uploaded_image("seven.jpg", size=(100, 100)),
                caption="Седьмое фото",
            )
        self.assertEqual(
            self.service.photos.count(), ServicePhoto.MAX_PHOTOS
        )

    def test_upload_view_rejects_when_limit_is_reached(self):
        for index in range(ServicePhoto.MAX_PHOTOS):
            self.make_photo(caption=f"Фото {index + 1}")

        response = self.client.post(
            reverse(
                "shop:service_photo_upload",
                kwargs={"pk": self.service.pk},
            ),
            {"images": uploaded_image("extra.jpg", size=(100, 100))},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("6", response.json()["error"])
        self.assertEqual(
            self.service.photos.count(), ServicePhoto.MAX_PHOTOS
        )

    def test_upload_to_foreign_service_is_404(self):
        response = self.client.post(
            reverse(
                "shop:service_photo_upload",
                kwargs={"pk": self.foreign_service.pk},
            ),
            {"images": uploaded_image("hack.jpg", size=(100, 100))},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.foreign_service.photos.exists())

    def test_invalid_image_format_is_rejected(self):
        response = self.client.post(
            reverse(
                "shop:service_photo_upload",
                kwargs={"pk": self.service.pk},
            ),
            {
                "images": uploaded_image(
                    "animation.gif", size=(100, 100), image_format="GIF"
                )
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JPG", response.json()["error"])
        self.assertFalse(self.service.photos.exists())

    def test_oversized_source_is_rejected(self):
        class Oversized:
            size = ServicePhoto.MAX_SOURCE_SIZE + 1
            name = "big.jpg"

        with self.assertRaises(ValidationError):
            ServicePhoto.validate_source_image(Oversized())

    def test_delete_removes_file_from_disk(self):
        photo = self.make_photo()
        path = Path(photo.image.path)
        self.assertTrue(path.exists())

        response = self.client.post(
            reverse(
                "shop:service_photo_delete",
                kwargs={"pk": photo.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServicePhoto.objects.filter(pk=photo.pk).exists())
        self.assertFalse(path.exists())

    def test_caption_can_be_updated(self):
        photo = self.make_photo(caption="Старая подпись")
        response = self.client.post(
            reverse(
                "shop:service_photo_caption",
                kwargs={"pk": photo.pk},
            ),
            {"caption": "Новая подпись"},
        )
        self.assertEqual(response.status_code, 200)
        photo.refresh_from_db()
        self.assertEqual(photo.caption, "Новая подпись")

    def test_foreign_photo_cannot_be_changed_or_deleted(self):
        foreign_photo = ServicePhoto.objects.create(
            service=self.foreign_service,
            image=uploaded_image("foreign.jpg", size=(100, 100)),
            caption="Чужая",
        )
        caption_response = self.client.post(
            reverse(
                "shop:service_photo_caption",
                kwargs={"pk": foreign_photo.pk},
            ),
            {"caption": "Взлом"},
        )
        delete_response = self.client.post(
            reverse(
                "shop:service_photo_delete",
                kwargs={"pk": foreign_photo.pk},
            )
        )
        self.assertEqual(caption_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        foreign_photo.refresh_from_db()
        self.assertEqual(foreign_photo.caption, "Чужая")

    def test_services_page_shows_photo_counter_and_panel(self):
        self.make_photo(caption="Красивая работа")

        page = self.client.get(reverse("shop:services"))
        self.assertContains(page, "Фото: 1 из 6")
        self.assertContains(page, "service-photo-thumb")

        panel = self.client.get(
            f"{reverse('shop:services')}?photos={self.service.pk}"
        )
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "Фотографии услуги")
        self.assertContains(panel, "Фото: 1 из 6")
        self.assertContains(panel, "Красивая работа")
        self.assertContains(panel, 'enctype="multipart/form-data"')
        self.assertContains(panel, "Загрузить фото")

    def test_foreign_photos_panel_is_404(self):
        response = self.client.get(
            f"{reverse('shop:services')}?photos={self.foreign_service.pk}"
        )
        self.assertEqual(response.status_code, 404)

    def test_deleting_service_removes_photo_files(self):
        photo = self.make_photo()
        path = Path(photo.image.path)
        self.assertTrue(path.exists())

        response = self.client.post(
            reverse("shop:service_delete", kwargs={"pk": self.service.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(path.exists())


class PromoManagementTests(ShopBase):
    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user("promo-other", password="StrongPass123")
        self.promo = PromoOffer.objects.create(
            owner=self.user,
            title="Скидка на диагностику",
            description="Скидка 10% по промокоду.",
            badge_text="Акция",
            promo_code="DIAG10",
            target_url="https://partner.example/diag",
            is_featured=True,
        )

    def payload(self, **overrides):
        data = {
            "title": "Скидка на диагностику",
            "description": "Скидка 10% по промокоду.",
            "badge_text": "Акция",
            "promo_code": "DIAG10",
            "target_url": "https://partner.example/diag",
            "is_featured": "on",
            "expires_at": (timezone.localdate() + timedelta(days=10)).isoformat(),
            "is_active": "on",
        }
        data.update(overrides)
        return data

    def test_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("shop:promos"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_page_shows_only_own_promos_and_clicks(self):
        PromoOffer.objects.filter(pk=self.promo.pk).update(clicks_count=7)
        PromoOffer.objects.create(
            owner=self.other, title="Чужая акция", badge_text="Партнёр"
        )
        response = self.client.get(reverse("shop:promos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Скидка на диагностику")
        self.assertContains(response, "<strong>7</strong>")
        self.assertNotContains(response, "Чужая акция")
        self.assertEqual(
            [promo.pk for promo in response.context["promos"]], [self.promo.pk]
        )

    def test_create_promo_assigns_owner(self):
        response = self.client.post(
            reverse("shop:promo_save"),
            self.payload(
                title="Бонус к первому визиту",
                badge_text="Бонус",
                promo_code="FIRST",
                target_url="https://partner.example/first",
                is_featured="",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        promo = PromoOffer.objects.get(
            owner=self.user, title="Бонус к первому визиту"
        )
        self.assertEqual(promo.badge_text, "Бонус")
        self.assertEqual(promo.promo_code, "FIRST")
        self.assertEqual(promo.target_url, "https://partner.example/first")
        self.assertFalse(promo.is_featured)
        self.assertTrue(promo.is_active)

    def test_create_promo_without_title_is_rejected(self):
        response = self.client.post(
            reverse("shop:promo_save"), self.payload(title="   ")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json()["errors"])
        self.assertFalse(
            PromoOffer.objects.filter(owner=self.user, title="").exists()
        )

    def test_invalid_target_url_is_rejected(self):
        response = self.client.post(
            reverse("shop:promo_save"),
            self.payload(target_url="javascript:alert(1)"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("target_url", response.json()["errors"])

    def test_edit_promo(self):
        response = self.client.post(
            reverse("shop:promo_save"),
            self.payload(
                id=self.promo.pk,
                title="Обновлённая акция",
                badge_text="Партнёр",
                is_featured="",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.title, "Обновлённая акция")
        self.assertEqual(self.promo.badge_text, "Партнёр")
        self.assertFalse(self.promo.is_featured)
        self.assertEqual(self.promo.owner, self.user)

    def test_edit_foreign_promo_is_404(self):
        foreign = PromoOffer.objects.create(owner=self.other, title="Чужая")
        response = self.client.post(
            reverse("shop:promo_save"),
            self.payload(id=foreign.pk, title="Взлом"),
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.title, "Чужая")

    def test_toggle_promo(self):
        response = self.client.post(
            reverse("shop:promo_toggle", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.promo.refresh_from_db()
        self.assertFalse(self.promo.is_active)

        response = self.client.post(
            reverse("shop:promo_toggle", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.promo.refresh_from_db()
        self.assertTrue(self.promo.is_active)

    def test_toggle_foreign_promo_is_404(self):
        foreign = PromoOffer.objects.create(owner=self.other, title="Чужая")
        response = self.client.post(
            reverse("shop:promo_toggle", kwargs={"pk": foreign.pk})
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_delete_promo(self):
        response = self.client.post(
            reverse("shop:promo_delete", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PromoOffer.objects.filter(pk=self.promo.pk).exists())

    def test_delete_foreign_promo_is_404(self):
        foreign = PromoOffer.objects.create(owner=self.other, title="Чужая")
        response = self.client.post(
            reverse("shop:promo_delete", kwargs={"pk": foreign.pk})
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PromoOffer.objects.filter(pk=foreign.pk).exists())


class PromoClickTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("click-master", password="StrongPass123")
        cls.promo = PromoOffer.objects.create(
            owner=cls.user,
            title="Партнёрский бонус",
            target_url="https://partner.example/bonus",
        )

    def test_click_increments_counter_and_redirects(self):
        response = self.client.get(
            reverse("shop:promo_go", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://partner.example/bonus")
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.clicks_count, 1)

    def test_repeated_clicks_are_counted(self):
        url = reverse("shop:promo_go", kwargs={"pk": self.promo.pk})
        self.client.get(url)
        self.client.get(url)
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.clicks_count, 2)

    def test_inactive_promo_does_not_count(self):
        PromoOffer.objects.filter(pk=self.promo.pk).update(is_active=False)
        response = self.client.get(
            reverse("shop:promo_go", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 404)
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.clicks_count, 0)

    def test_expired_promo_does_not_count(self):
        PromoOffer.objects.filter(pk=self.promo.pk).update(
            expires_at=timezone.localdate() - timedelta(days=1)
        )
        response = self.client.get(
            reverse("shop:promo_go", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 404)
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.clicks_count, 0)

    def test_promo_without_target_url_is_not_clickable(self):
        PromoOffer.objects.filter(pk=self.promo.pk).update(target_url="")
        response = self.client.get(
            reverse("shop:promo_go", kwargs={"pk": self.promo.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_promo_is_404(self):
        response = self.client.get(
            reverse("shop:promo_go", kwargs={"pk": 999999})
        )
        self.assertEqual(response.status_code, 404)


class AnalyticsTests(ShopBase):
    def test_today_finance_and_top_services(self):
        self.make_order(
            stage=self.stages[-1],
            scheduled_at=local_at(0, 10),
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("2000.00"),
            payment_method=Order.PAYMENT_CASH,
        )
        self.make_order(
            stage=self.stages[1],
            scheduled_at=local_at(0, 11),
            total_amount=Decimal("3000.00"),
            paid_amount=Decimal("1000.00"),
            payment_method=Order.PAYMENT_CARD,
        )
        self.make_order(
            stage=self.stages[0],
            scheduled_at=local_at(0, 12),
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("0.00"),
        )
        second = Service.objects.create(
            owner=self.user,
            name="Полировка",
            price=Decimal("5000.00"),
            cost_price=Decimal("1000.00"),
        )
        self.make_order(
            service=second,
            service_name=second.name,
            stage=self.stages[-1],
            scheduled_at=local_at(0, 13),
            total_amount=Decimal("5000.00"),
            paid_amount=Decimal("5000.00"),
            payment_method=Order.PAYMENT_CASH,
        )

        data = build_analytics(self.user, "today")
        finance = data["finance"]
        self.assertEqual(finance["revenue"], Decimal("8000.00"))
        self.assertEqual(finance["cost"], Decimal("2000.00"))
        self.assertEqual(finance["profit"], Decimal("6000.00"))
        self.assertEqual(finance["paid_orders"], 3)
        self.assertEqual(finance["cash"]["total"], Decimal("7000.00"))
        self.assertEqual(finance["cash"]["count"], 2)
        self.assertEqual(finance["card"]["total"], Decimal("1000.00"))
        self.assertEqual(finance["debt_total"], Decimal("3000.00"))
        self.assertEqual(finance["completed_count"], 2)
        self.assertEqual(data["top_services"][0]["name"], "Полировка")
        self.assertEqual(data["top_services"][0]["revenue"], Decimal("5000.00"))
        self.assertEqual(data["top_services"][1]["name"], "Компьютерная диагностика")

    def test_period_bounds(self):
        week_order = self.make_order(
            scheduled_at=local_at(-3),
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("777.00"),
        )
        self.make_order(
            scheduled_at=local_at(-40),
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("111.00"),
        )

        today = build_analytics(self.user, "today")
        week = build_analytics(self.user, "week")
        month = build_analytics(self.user, "month")
        self.assertEqual(today["finance"]["revenue"], Decimal("0.00"))
        self.assertEqual(week["finance"]["revenue"], week_order.paid_amount)
        self.assertEqual(month["finance"]["revenue"], week_order.paid_amount)

    def test_invalid_period_defaults_to_today(self):
        data = build_analytics(self.user, "year")
        self.assertEqual(data["period"], "today")

    def test_other_users_orders_are_excluded(self):
        other = User.objects.create_user("other", password="StrongPass123")
        other_client = Client.objects.create(
            owner=other, name="Чужой", phone="+7 900 000-00-01"
        )
        Order.objects.create(
            owner=other,
            client=other_client,
            stage=PipelineStage.objects.filter(owner=other).first(),
            scheduled_at=local_at(0),
            total_amount=Decimal("5000.00"),
            paid_amount=Decimal("5000.00"),
        )
        data = build_analytics(self.user, "today")
        self.assertEqual(data["finance"]["revenue"], Decimal("0.00"))

    def test_missing_cost_is_reported(self):
        service = Service.objects.create(
            owner=self.user, name="Без себестоимости", price=Decimal("1000.00")
        )
        self.make_order(
            service=service,
            service_name=service.name,
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("1000.00"),
        )
        data = build_analytics(self.user, "today")
        self.assertEqual(data["finance"]["missing_cost_count"], 1)

    def test_analytics_page(self):
        self.make_order(
            scheduled_at=local_at(0),
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("2000.00"),
        )
        response = self.client.get(reverse("shop:analytics"), {"period": "today"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выручка")
        self.assertContains(response, "Топ-5 услуг")
        self.assertEqual(response.context["period"], "today")


class SeedDemoTests(TestCase):
    def test_seed_demo_creates_data_and_is_idempotent(self):
        call_command("seed_demo", verbosity=0)

        user = User.objects.get(username="admin")
        self.assertTrue(user.check_password("admin123"))
        profile = MasterProfile.objects.get(user=user)
        self.assertEqual(profile.slug, "demo-service")
        self.assertEqual(profile.business_name, "Автосервис «Сфера»")
        self.assertTrue(profile.phone)

        services = Service.objects.filter(owner=user)
        self.assertEqual(services.count(), 5)
        self.assertTrue(services.filter(name="Развал-схождение").exists())
        names = [service.name.casefold() for service in services]
        self.assertFalse(any("кухн" in name for name in names))

        clients = Client.objects.filter(owner=user)
        self.assertEqual(clients.count(), 3)
        self.assertTrue(all(client.identifier for client in clients))

        self.assertEqual(Order.objects.filter(owner=user).count(), 8)
        stages = PipelineStage.objects.filter(owner=user).order_by("order", "id")
        self.assertEqual(stages.count(), 5)
        self.assertEqual(stages.last().name, "Выполнено")

        kinds = [item["kind"] for item in build_suggestions(user, profile)]
        self.assertEqual(kinds, ["debt", "stale", "sleeping"])

        analytics = build_analytics(user, "month")
        self.assertGreater(analytics["finance"]["revenue"], Decimal("0.00"))

        home = self.client.get(reverse("home"))
        self.assertContains(home, "Автосервис «Сфера»")
        self.assertContains(
            home, reverse("public_master", kwargs={"slug": "demo-service"})
        )

        # Повторный запуск не должен дублировать данные.
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Service.objects.filter(owner=user).count(), 5)
        self.assertEqual(Client.objects.filter(owner=user).count(), 3)
        self.assertEqual(Order.objects.filter(owner=user).count(), 8)

        login = self.client.post(
            reverse("login"), {"username": "admin", "password": "admin123"}
        )
        self.assertRedirects(login, reverse("shop:dashboard"))

        public = self.client.get(
            reverse("public_master", kwargs={"slug": "demo-service"})
        )
        self.assertEqual(public.status_code, 200)
        self.assertContains(public, "Автосервис «Сфера»")


class AccessTests(ShopBase):
    def test_pages_require_login(self):
        self.client.logout()
        for url in (
            reverse("shop:dashboard"),
            reverse("shop:services"),
            reverse("shop:analytics"),
            reverse("shop:order_create"),
            reverse("settings"),
            reverse("core:client_list"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"], url)

    def test_authenticated_pages_open(self):
        for url in (
            reverse("shop:dashboard"),
            reverse("shop:services"),
            reverse("shop:analytics"),
            reverse("shop:order_create"),
            reverse("settings"),
            reverse("core:client_list"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

"""Тесты профиля мастера, клиентов, настроек и публичной страницы."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import Order, PipelineStage, Service

from .forms import PublicBookingForm
from .models import Client, MasterProfile, unique_slug_for

User = get_user_model()


def local_at(days: int = 0, hour: int = 12, minute: int = 0):
    base = timezone.localtime() + timedelta(days=days)
    naive = datetime.combine(base.date(), time(hour, minute))
    return timezone.make_aware(naive, timezone.get_current_timezone())


class ProfileSignalTests(TestCase):
    def test_profile_and_quick_funnel_created_with_user(self):
        user = User.objects.create_user("ivan", password="StrongPass123")

        profile = MasterProfile.objects.get(user=user)
        self.assertEqual(profile.slug, "ivan")
        self.assertEqual(profile.business_name, "ivan")
        self.assertTrue(profile.is_public)

        stages = list(PipelineStage.objects.filter(owner=user).order_by("order"))
        self.assertEqual(
            [stage.name for stage in stages],
            ["Новая заявка", "Подтверждено", "В работе", "Выполнено"],
        )
        self.assertTrue(stages[-1].is_final)
        self.assertEqual([stage.order for stage in stages], [1, 2, 3, 4])

    def test_cyrillic_username_gets_latin_slug(self):
        user = User.objects.create_user("мастер", password="StrongPass123")
        profile = MasterProfile.objects.get(user=user)
        self.assertEqual(profile.slug, "master")
        self.assertTrue(profile.slug.isascii())

    def test_unique_slug_for_avoids_collisions(self):
        first = User.objects.create_user("master", password="StrongPass123")
        second = User.objects.create_user("master2", password="StrongPass123")
        self.assertEqual(MasterProfile.objects.get(user=first).slug, "master")
        generated = unique_slug_for("master")
        self.assertNotEqual(generated, "master")
        self.assertTrue(generated.startswith("master-"))
        self.assertNotEqual(MasterProfile.objects.get(user=second).slug, "master")


class HomePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.public_user = User.objects.create_user(
            "public-studio", password="StrongPass123"
        )
        profile = MasterProfile.objects.get(user=cls.public_user)
        profile.business_name = "Публичная студия"
        profile.slug = "public-studio"
        profile.description = "Стрижки и укладка в центре города."
        profile.is_public = True
        profile.save()
        Service.objects.create(
            owner=cls.public_user,
            name="Стрижка",
            price=Decimal("2500.00"),
            is_active=True,
        )

        cls.private_user = User.objects.create_user(
            "private-studio", password="StrongPass123"
        )
        private = MasterProfile.objects.get(user=cls.private_user)
        private.business_name = "Скрытая студия"
        private.slug = "private-studio"
        private.is_public = False
        private.save()

    def test_home_is_public_landing_for_anonymous(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сфера")
        self.assertContains(response, "Создать страницу бизнеса")
        self.assertContains(response, "Войти")
        self.assertContains(response, "Публичная студия")

    def test_home_showcase_respects_public_flag(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Публичная студия")
        self.assertNotContains(response, "Скрытая студия")
        self.assertContains(
            response, reverse("public_master", kwargs={"slug": "public-studio"})
        )

    def test_authenticated_user_redirected_to_dashboard(self):
        self.client.force_login(self.public_user)
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("shop:dashboard"))

    def test_root_is_not_forced_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(reverse("login"), response.get("Location", ""))


class RegistrationTests(TestCase):
    url = reverse("register")

    def test_register_page_opens(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Создать страницу бизнеса")

    def test_register_creates_profile_stages_and_logs_in(self):
        response = self.client.post(
            self.url,
            {
                "username": "new-master",
                "business_name": "Студия керамики",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "funnel_template": "quick",
            },
        )
        self.assertRedirects(
            response,
            f"{reverse('shop:services')}?onboarding=1",
            fetch_redirect_response=False,
        )

        user = User.objects.get(username="new-master")
        self.assertEqual(user.master_profile.business_name, "Студия керамики")
        self.assertEqual(user.master_profile.slug, "new-master")
        self.assertEqual(PipelineStage.objects.filter(owner=user).count(), 4)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        # Онбординг начинается с пустой базы — без демо-услуг и записей.
        self.assertFalse(user.services.exists())
        self.assertFalse(user.clients.exists())
        self.assertFalse(user.orders.exists())

    def test_registration_opens_services_with_onboarding_banner(self):
        self.client.post(
            self.url,
            {
                "username": "onboarding",
                "business_name": "Новая компания",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "funnel_template": "quick",
            },
        )
        response = self.client.get(
            f"{reverse('shop:services')}?onboarding=1"
        )
        self.assertContains(
            response,
            "Шаг 1: Создайте хотя бы одну услугу, чтобы клиенты могли "
            "записываться на вашу страницу",
        )

    def test_register_with_complex_funnel(self):
        self.client.post(
            self.url,
            {
                "username": "kitchen",
                "business_name": "Кухни на заказ",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "funnel_template": "complex",
            },
        )
        user = User.objects.get(username="kitchen")
        stages = list(
            PipelineStage.objects.filter(owner=user).order_by("order", "id")
        )
        self.assertEqual(
            [stage.name for stage in stages],
            [
                "Новая заявка",
                "Замер / Осмотр",
                "Предоплата",
                "В работе / Изготовление",
                "Выполнено",
            ],
        )
        self.assertTrue(stages[-1].is_final)

    def test_duplicate_username_is_rejected_case_insensitively(self):
        User.objects.create_user("taken", password="StrongPass123")
        response = self.client.post(
            self.url,
            {
                "username": "TAKEN",
                "business_name": "Дубль",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "funnel_template": "quick",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("занят", response.context["form"].errors["username"][0])
        self.assertEqual(User.objects.filter(username__iexact="taken").count(), 1)

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "username": "someone",
                "business_name": "Мастерская",
                "password1": "StrongPass123",
                "password2": "OtherPass123",
                "funnel_template": "quick",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="someone").exists())

    def test_authenticated_user_redirected_from_register(self):
        user = User.objects.create_user("logged", password="StrongPass123")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("shop:dashboard"))


class ClientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("master", password="StrongPass123")
        cls.other = User.objects.create_user("other", password="StrongPass123")
        cls.client_obj = Client.objects.create(
            owner=cls.user,
            name="Иван Петров",
            phone="+7 999 123-45-67",
            identifier="А123ВС 77",
            notes="Любит масло 5W-30",
        )
        cls.other_client = Client.objects.create(
            owner=cls.other,
            name="Секретный Клиент",
            phone="+7 900 000-00-00",
            identifier="Х000ХХ 00",
        )
        cls.stages = list(
            PipelineStage.objects.filter(owner=cls.user).order_by("order", "id")
        )
        cls.service = Service.objects.create(
            owner=cls.user,
            name="Диагностика",
            price=Decimal("2000.00"),
            cost_price=Decimal("500.00"),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("core:client_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_list_shows_only_own_clients(self):
        response = self.client.get(reverse("core:client_list"))
        self.assertContains(response, "Иван Петров")
        self.assertNotContains(response, "Секретный Клиент")

    def test_search_by_name_phone_and_identifier(self):
        for query in ("иван", "123-45", "а123"):
            response = self.client.get(reverse("core:client_list"), {"q": query})
            self.assertContains(response, "Иван Петров", msg_prefix=query)
            self.assertNotContains(response, "Секретный Клиент")

    def test_search_returns_nothing_for_unknown_query(self):
        response = self.client.get(reverse("core:client_list"), {"q": "неттакого"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ничего не найдено")

    def test_detail_shows_history_and_total_paid(self):
        Order.objects.create(
            owner=self.user,
            client=self.client_obj,
            service=self.service,
            service_name=self.service.name,
            stage=self.stages[-1],
            scheduled_at=local_at(-10),
            total_amount=Decimal("2000.00"),
            paid_amount=Decimal("1500.00"),
            payment_method=Order.PAYMENT_CASH,
            work_details="Заменено масло и фильтры",
        )
        Order.objects.create(
            owner=self.user,
            client=self.client_obj,
            service=self.service,
            service_name=self.service.name,
            stage=self.stages[0],
            scheduled_at=local_at(1),
            total_amount=Decimal("3000.00"),
            paid_amount=Decimal("500.00"),
            work_details="Диагностика подвески",
        )

        response = self.client.get(
            reverse("core:client_detail", kwargs={"pk": self.client_obj.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "История обслуживания")
        self.assertContains(response, "Заменено масло и фильтры")
        self.assertContains(response, "Диагностика подвески")
        self.assertEqual(response.context["total_paid"], Decimal("2000.00"))
        self.assertEqual(response.context["debt"], Decimal("3000.00"))
        self.assertEqual(len(response.context["orders"]), 2)

    def test_other_users_client_is_hidden(self):
        response = self.client.get(
            reverse("core:client_detail", kwargs={"pk": self.other_client.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_add_client_assigns_owner(self):
        response = self.client.post(
            reverse("core:client_add"),
            {
                "name": "Анна Смирнова",
                "phone": "+7 912 555-10-20",
                "identifier": "VIN XW8ZZZ61ZJG000123",
                "notes": "Кухня 3,2 м",
            },
        )
        created = Client.objects.get(name="Анна Смирнова")
        self.assertEqual(created.owner, self.user)
        self.assertEqual(created.identifier, "VIN XW8ZZZ61ZJG000123")
        self.assertRedirects(
            response,
            reverse("core:client_detail", kwargs={"pk": created.pk}),
        )

    def test_duplicate_phone_in_different_format_is_rejected(self):
        response = self.client.post(
            reverse("core:client_add"),
            {
                "name": "Клон",
                "phone": "89991234567",
                "identifier": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("уже есть", response.context["form"].errors["phone"][0])
        self.assertEqual(Client.objects.filter(owner=self.user).count(), 1)

    def test_edit_client(self):
        response = self.client.post(
            reverse("core:client_edit", kwargs={"pk": self.client_obj.pk}),
            {
                "name": "Иван Петров",
                "phone": "+7 999 123-45-67",
                "identifier": "В456ОР 99",
                "notes": "Новый VIN",
            },
        )
        self.assertRedirects(
            response,
            reverse("core:client_detail", kwargs={"pk": self.client_obj.pk}),
        )
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.identifier, "В456ОР 99")
        self.assertEqual(self.client_obj.notes, "Новый VIN")

    def test_delete_client_without_orders(self):
        client = Client.objects.create(
            owner=self.user, name="Без истории", phone="+7 901 000-00-01"
        )
        response = self.client.post(
            reverse("core:client_delete", kwargs={"pk": client.pk})
        )
        self.assertRedirects(response, reverse("core:client_list"))
        self.assertFalse(Client.objects.filter(pk=client.pk).exists())

    def test_delete_client_with_orders_is_blocked(self):
        Order.objects.create(
            owner=self.user,
            client=self.client_obj,
            service=self.service,
            stage=self.stages[0],
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        response = self.client.post(
            reverse("core:client_delete", kwargs={"pk": self.client_obj.pk})
        )
        self.assertRedirects(
            response,
            reverse("core:client_detail", kwargs={"pk": self.client_obj.pk}),
        )
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())


class SettingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("master", password="StrongPass123")
        cls.profile = MasterProfile.objects.get(user=cls.user)
        cls.profile.business_name = "Старая мастерская"
        cls.profile.slug = "old-master"
        cls.profile.save()
        cls.stages = list(
            PipelineStage.objects.filter(owner=cls.user).order_by("order", "id")
        )
        cls.service = Service.objects.create(
            owner=cls.user, name="Услуга", price=Decimal("1000.00")
        )

    def setUp(self):
        self.client.force_login(self.user)

    def profile_payload(self, **overrides):
        payload = {
            "action": "profile",
            "slug": "new-master",
            "business_name": "Студия «Глина»",
            "description": "Лепим посуду и проводим мастер-классы.",
            "phone": "+7 (999) 111-22-33",
            "telegram": "@clay_studio",
            "address": "г. Казань, ул. Гончарная, 1",
            "theme": "rose",
            "work_hours": "10:00 - 19:00",
            "is_public": "on",
        }
        payload.update(overrides)
        return payload

    def test_settings_page_opens(self):
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Публичная страница")
        self.assertContains(response, "Этапы воронки")
        self.assertContains(response, "Быстрые услуги")
        self.assertContains(response, "Показывать компанию на главной странице")

    def test_profile_update(self):
        response = self.client.post(reverse("settings"), self.profile_payload())
        self.assertRedirects(response, reverse("settings"))

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.slug, "new-master")
        self.assertEqual(self.profile.business_name, "Студия «Глина»")
        self.assertEqual(self.profile.theme, "rose")
        self.assertTrue(self.profile.is_public)
        self.assertEqual(self.profile.telegram_url, "https://t.me/clay_studio")

    def test_company_can_be_hidden_from_showcase(self):
        self.client.post(
            reverse("settings"), self.profile_payload(is_public="")
        )
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_public)

        self.client.logout()
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, "Студия «Глина»")

        public = self.client.get(
            reverse("public_master", kwargs={"slug": "new-master"})
        )
        self.assertEqual(public.status_code, 200)
        self.assertContains(public, "theme-rose")

    def test_invalid_cyrillic_slug_is_rejected(self):
        response = self.client.post(
            reverse("settings"), self.profile_payload(slug="кухни")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("латинских", response.context["form"].errors["slug"][0])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.slug, "old-master")

    def test_duplicate_slug_is_rejected(self):
        other = User.objects.create_user("taken", password="StrongPass123")
        MasterProfile.objects.filter(user=other).update(slug="busy-slug")

        response = self.client.post(
            reverse("settings"), self.profile_payload(slug="busy-slug")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("занят", response.context["form"].errors["slug"][0])

    def test_invalid_theme_is_rejected(self):
        response = self.client.post(
            reverse("settings"), self.profile_payload(theme="neon")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("theme", response.context["form"].errors)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme, MasterProfile.THEME_BLUE)

    def test_stage_update(self):
        stage = self.stages[1]
        response = self.client.post(
            reverse("settings"),
            {
                "action": "stage_update",
                "stage_id": stage.pk,
                "name": "Согласовано",
                "color": "warning",
                "order": "7",
                "is_final": "",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        stage.refresh_from_db()
        self.assertEqual(stage.name, "Согласовано")
        self.assertEqual(stage.color, "warning")
        self.assertEqual(stage.order, 7)
        self.assertFalse(stage.is_final)

    def test_stage_add(self):
        response = self.client.post(
            reverse("settings"),
            {
                "action": "stage_add",
                "new_name": "Согласование",
                "new_color": "info",
                "new_order": "9",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        stage = PipelineStage.objects.get(owner=self.user, name="Согласование")
        self.assertEqual(stage.color, "info")
        self.assertEqual(stage.order, 9)

    def test_duplicate_stage_name_is_rejected(self):
        response = self.client.post(
            reverse("settings"),
            {
                "action": "stage_add",
                "new_name": "новая заявка",
                "new_color": "primary",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        stages = PipelineStage.objects.filter(owner=self.user)
        self.assertEqual(
            sum(
                1
                for stage in stages
                if stage.name.strip().casefold() == "новая заявка"
            ),
            1,
        )

    def test_stage_with_orders_cannot_be_deleted(self):
        Order.objects.create(
            owner=self.user,
            client=Client.objects.create(
                owner=self.user, name="Клиент", phone="+7 999 000-00-11"
            ),
            service=self.service,
            stage=self.stages[0],
            scheduled_at=local_at(0),
            total_amount=Decimal("1000.00"),
        )
        response = self.client.post(
            reverse("settings"),
            {"action": "stage_delete", "stage_id": self.stages[0].pk},
        )
        self.assertRedirects(response, reverse("settings"))
        self.assertTrue(
            PipelineStage.objects.filter(pk=self.stages[0].pk).exists()
        )

    def test_empty_stage_can_be_deleted(self):
        stage = self.stages[1]
        response = self.client.post(
            reverse("settings"),
            {"action": "stage_delete", "stage_id": stage.pk},
        )
        self.assertRedirects(response, reverse("settings"))
        self.assertFalse(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_last_stage_cannot_be_deleted(self):
        for stage in self.stages[:-1]:
            PipelineStage.objects.filter(pk=stage.pk).delete()
        last = PipelineStage.objects.filter(owner=self.user).first()

        response = self.client.post(
            reverse("settings"),
            {"action": "stage_delete", "stage_id": last.pk},
        )
        self.assertRedirects(response, reverse("settings"))
        self.assertTrue(PipelineStage.objects.filter(pk=last.pk).exists())

    def test_load_complex_template_adds_missing_stages(self):
        response = self.client.post(
            reverse("settings"),
            {"action": "load_template", "template": "complex"},
        )
        self.assertRedirects(response, reverse("settings"))
        names = set(
            PipelineStage.objects.filter(owner=self.user).values_list(
                "name", flat=True
            )
        )
        for name in (
            "Замер / Осмотр",
            "Предоплата",
            "В работе / Изготовление",
        ):
            self.assertIn(name, names)
        self.assertEqual(
            PipelineStage.objects.filter(owner=self.user, name="Новая заявка").count(),
            1,
        )


class PublicPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("clay", password="StrongPass123")
        cls.profile = MasterProfile.objects.get(user=cls.user)
        cls.profile.business_name = "Студия «Глина»"
        cls.profile.slug = "clay-studio"
        cls.profile.description = "Керамика ручной работы и мастер-классы."
        cls.profile.phone = "+7 (999) 111-22-33"
        cls.profile.telegram = "@clay_studio"
        cls.profile.address = "г. Казань, ул. Гончарная, 1"
        cls.profile.theme = MasterProfile.THEME_EMERALD
        cls.profile.work_hours = "10:00 - 19:00"
        cls.profile.save()

        cls.active_service = Service.objects.create(
            owner=cls.user,
            name="Мастер-класс по гончарному кругу",
            price=Decimal("3500.00"),
            cost_price=Decimal("700.00"),
            duration_minutes=120,
            is_active=True,
        )
        cls.hidden_service = Service.objects.create(
            owner=cls.user,
            name="Скрытая услуга",
            price=Decimal("100.00"),
            is_active=False,
        )
        cls.stages = list(
            PipelineStage.objects.filter(owner=cls.user).order_by("order", "id")
        )

    def setUp(self):
        self.url = reverse("public_master", kwargs={"slug": "clay-studio"})

    def booking_payload(self, **overrides):
        scheduled = local_at(1, 14, 30)
        payload = {
            "service": self.active_service.pk,
            "scheduled_at": scheduled.strftime("%Y-%m-%dT%H:%M"),
            "name": "Мария Иванова",
            "phone": "+7 912 000-11-22",
        }
        payload.update(overrides)
        return payload

    def test_public_page_is_available_without_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Студия «Глина»")
        self.assertContains(response, "Керамика ручной работы")
        self.assertContains(response, "Мастер-класс по гончарному кругу")
        self.assertContains(response, "theme-emerald")
        self.assertContains(response, "Имя и фамилия")
        self.assertContains(response, "Дата и время")
        self.assertContains(
            response, "Онлайн-запись работает на платформе"
        )
        self.assertNotContains(response, "Скрытая услуга")

    def test_public_page_uses_sfera_url_and_legacy_redirect(self):
        self.assertTrue(self.url.startswith("/s/clay-studio/"))
        legacy = self.client.get("/m/clay-studio/")
        self.assertEqual(legacy.status_code, 301)
        self.assertEqual(legacy["Location"], self.url)

    def test_per_service_button_preselects_service(self):
        response = self.client.get(
            self.url, {"service": self.active_service.pk}
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(
            str(form["service"].value()), str(self.active_service.pk)
        )
        self.assertContains(
            response, f'data-book-service="{self.active_service.pk}"'
        )
        self.assertContains(response, "data-book-general")

    def test_unknown_slug_returns_404(self):
        response = self.client.get(
            reverse("public_master", kwargs={"slug": "no-such-master"})
        )
        self.assertEqual(response.status_code, 404)

    def test_booking_creates_client_and_order(self):
        response = self.client.post(self.url, self.booking_payload())
        self.assertRedirects(
            response, self.url + "?booked=1", fetch_redirect_response=False
        )

        client = Client.objects.get(owner=self.user, phone="+7 912 000-11-22")
        self.assertEqual(client.name, "Мария Иванова")

        order = Order.objects.get(owner=self.user, client=client)
        self.assertEqual(order.service, self.active_service)
        self.assertEqual(order.service_name, "Мастер-класс по гончарному кругу")
        self.assertEqual(order.stage, self.stages[0])
        self.assertEqual(order.total_amount, Decimal("3500.00"))
        self.assertEqual(order.paid_amount, Decimal("0.00"))
        self.assertEqual(order.payment_method, Order.PAYMENT_NONE)

    def test_existing_client_matched_by_phone_format(self):
        existing = Client.objects.create(
            owner=self.user,
            name="Мария Иванова",
            phone="+7 (912) 000-11-22",
        )
        self.client.post(
            self.url,
            self.booking_payload(phone="89120001122"),
        )
        self.assertEqual(Client.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(
            Order.objects.filter(owner=self.user, client=existing).count(), 1
        )

    def test_past_date_is_rejected(self):
        past = local_at(-1, 14, 30).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            self.url, self.booking_payload(scheduled_at=past)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Order.objects.filter(owner=self.user).exists(),
            "Запись в прошлом не должна создаваться",
        )
        self.assertIn("scheduled_at", response.context["form"].errors)

    def test_foreign_service_is_rejected(self):
        other = User.objects.create_user("other", password="StrongPass123")
        foreign = Service.objects.create(
            owner=other, name="Чужая услуга", price=Decimal("1000.00")
        )
        response = self.client.post(
            self.url, self.booking_payload(service=foreign.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("service", response.context["form"].errors)
        self.assertFalse(Order.objects.filter(owner=self.user).exists())

    def test_honeypot_blocks_spam(self):
        response = self.client.post(
            self.url, self.booking_payload(website="http://spam.example")
        )
        self.assertRedirects(
            response, self.url + "?booked=1", fetch_redirect_response=False
        )
        self.assertFalse(Order.objects.filter(owner=self.user).exists())

    def test_page_without_active_services(self):
        Service.objects.filter(owner=self.user).update(is_active=False)
        response = self.client.get(self.url)
        self.assertContains(response, "Онлайн-запись временно недоступна")
        self.assertNotContains(response, 'name="service"')

    def test_form_stage_is_first_stage(self):
        form = PublicBookingForm(
            data=self.booking_payload(),
            services=Service.objects.filter(owner=self.user, is_active=True),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["service"], self.active_service)
        self.assertGreater(form.cleaned_data["scheduled_at"], timezone.now())

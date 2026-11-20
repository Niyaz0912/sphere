"""Демо-данные Сфера: мастер admin, воронка, услуги, клиенты и заказы."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Client, MasterProfile, unique_slug_for
from shop.models import Order, PipelineStage, Service


class Command(BaseCommand):
    help = "Создаёт демо-компанию admin/admin123 со страницей /s/demo-service/."

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username="admin")
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password("admin123")
        user.save()

        profile = MasterProfile.for_user(user)
        profile.business_name = "Автосервис «Сфера»"
        profile.slug = "demo-service"
        if (
            MasterProfile.objects.exclude(pk=profile.pk)
            .filter(slug=profile.slug)
            .exists()
        ):
            profile.slug = unique_slug_for(
                user.get_username(), base="demo-service", exclude_pk=profile.pk
            )
        profile.description = (
            "Автосервис полного цикла: плановое ТО, компьютерная диагностика, "
            "шиномонтаж, развал-схождение и полировка кузова. Работаем аккуратно, "
            "согласовываем каждую работу и держим вас в курсе."
        )
        profile.phone = "+7 (999) 123-45-67"
        profile.telegram = "@sfera_demo"
        profile.address = "г. Москва, ул. Гаражная, 12, бокс 3"
        profile.theme = MasterProfile.THEME_BLUE
        profile.work_hours = "09:00 - 20:00"
        profile.is_public = True
        profile.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Компания: admin / admin123 · {profile.get_absolute_url()}"
            )
        )

        if not Order.objects.filter(owner=user).exists():
            PipelineStage.apply_template(user, "complex", replace=True)

        services_data = [
            ("Замена масла и фильтров", "3500.00", "1800.00", 60),
            ("Компьютерная диагностика", "2500.00", "300.00", 45),
            ("Шиномонтаж и балансировка", "4000.00", "1200.00", 60),
            ("Полировка кузова", "8000.00", "2200.00", 120),
            ("Развал-схождение", "3000.00", "500.00", 60),
        ]
        services = {}
        for name, price, cost, duration in services_data:
            service, _ = Service.objects.update_or_create(
                owner=user,
                name=name,
                defaults={
                    "price": Decimal(price),
                    "cost_price": Decimal(cost),
                    "duration_minutes": duration,
                    "is_active": True,
                },
            )
            services[name] = service
        self.stdout.write(
            self.style.SUCCESS(f"Услуг в прайсе: {len(services_data)}")
        )

        clients_data = [
            (
                "Иван Петров",
                "+7 999 123-45-67",
                "А123ВС 77",
                "Toyota Camry 2019, масло 5W-30. Всегда просит показать старые фильтры.",
            ),
            (
                "Анна Смирнова",
                "+7 912 555-10-20",
                "В456ОР 99",
                "Volkswagen Polo, VIN XW8ZZZ61ZJG000123. "
                "Предпочитает утренние записи и карту.",
            ),
            (
                "Сергей Кузнецов",
                "+7 922 777-88-99",
                "В777АА 99",
                "Volkswagen Transporter. Удобно приезжать после 18:00.",
            ),
        ]
        clients = {}
        for name, phone, identifier, notes in clients_data:
            client, _ = Client.objects.update_or_create(
                owner=user,
                phone=phone,
                defaults={
                    "name": name,
                    "identifier": identifier,
                    "notes": notes,
                },
            )
            clients[name] = client
        self.stdout.write(
            self.style.SUCCESS(f"Клиентов в базе: {len(clients_data)}")
        )

        if Order.objects.filter(owner=user).exists():
            self.stdout.write(
                self.style.WARNING("Заказы уже есть — демо-записи не дублирую.")
            )
            self.stdout.write(
                self.style.SUCCESS("Готово. Вход: admin / admin123")
            )
            return

        stages = {
            stage.name: stage
            for stage in PipelineStage.objects.filter(owner=user)
        }
        now = timezone.localtime()

        def at(days: int, hour: int, minute: int = 0):
            moment = now + timedelta(days=days)
            return moment.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        def make_order(
            client_name,
            service_name,
            stage_name,
            scheduled,
            total,
            paid,
            method,
            details,
        ):
            service = services[service_name]
            return Order.objects.create(
                owner=user,
                client=clients[client_name],
                service=service,
                service_name=service.name,
                stage=stages[stage_name],
                scheduled_at=scheduled,
                total_amount=Decimal(total),
                paid_amount=Decimal(paid),
                payment_method=method,
                work_details=details,
            )

        orders = [
            make_order(
                "Иван Петров",
                "Замена масла и фильтров",
                "Выполнено",
                at(-3, 14, 0),
                "3500.00",
                "3500.00",
                Order.PAYMENT_CASH,
                "Масло Toyota 5W-30 (4,5 л), фильтры масляный и воздушный. "
                "Пробег 84 200 км. Следующая замена — через 10 000 км.",
            ),
            make_order(
                "Иван Петров",
                "Компьютерная диагностика",
                "В работе / Изготовление",
                at(0, 12, 30),
                "2500.00",
                "1000.00",
                Order.PAYMENT_CARD,
                "Ошибка P0420 — проверяем катализатор и датчик кислорода.",
            ),
            make_order(
                "Иван Петров",
                "Замена масла и фильтров",
                "Выполнено",
                at(-120, 11, 0),
                "3500.00",
                "3000.00",
                Order.PAYMENT_CASH,
                "Масло Shell Helix 5W-40, фильтр масляный. Клиент доплатит 500 ₽.",
            ),
            make_order(
                "Анна Смирнова",
                "Полировка кузова",
                "Новая заявка",
                at(1, 11, 0),
                "8000.00",
                "0.00",
                Order.PAYMENT_NONE,
                "Хочет убрать мелкие царапины после парковки.",
            ),
            make_order(
                "Анна Смирнова",
                "Развал-схождение",
                "Предоплата",
                at(10, 12, 0),
                "3000.00",
                "1000.00",
                Order.PAYMENT_CARD,
                "Сход-развал после ремонта подвески. Предоплата 1000 ₽.",
            ),
            make_order(
                "Сергей Кузнецов",
                "Компьютерная диагностика",
                "Замер / Осмотр",
                at(-95, 10, 0),
                "2500.00",
                "0.00",
                Order.PAYMENT_NONE,
                "Диагностика перед покупкой автомобиля. Клиент перенёс визит.",
            ),
            make_order(
                "Сергей Кузнецов",
                "Шиномонтаж и балансировка",
                "Выполнено",
                at(-95, 18, 0),
                "4000.00",
                "4000.00",
                Order.PAYMENT_CASH,
                'Комплект 17", балансировка, правка одного диска.',
            ),
            make_order(
                "Анна Смирнова",
                "Полировка кузова",
                "Выполнено",
                at(-100, 16, 0),
                "2500.00",
                "2500.00",
                Order.PAYMENT_CARD,
                "Экспресс-полировка перед продажей автомобиля.",
            ),
        ]

        # Заявка «зависла»: не обновлялась 6 дней — помощник её подсветит.
        stale = orders[3]
        Order.objects.filter(pk=stale.pk).update(
            updated_at=now - timedelta(days=6)
        )
        # Самая старая заявка Сергея — для правила «спящие клиенты».
        Order.objects.filter(pk=orders[5].pk).update(
            updated_at=now - timedelta(days=95)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Заказов создано: {len(orders)} (в работе, предоплата, выполнено, долг)"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Готово. Рабочий стол: http://127.0.0.1:8000/dashboard/ · "
                "страница компании: /s/demo-service/"
            )
        )

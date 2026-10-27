from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Booking, ClubSettings, Equipment, User, Zone
from core.services import calc_price

S = Booking.Status


class Command(BaseCommand):
    help = "Наполняет базу демо-данными: 2 зоны, 8 устройств, админ, 3 клиента, 15 броней."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="удалить старые демо-данные перед наполнением")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            Booking.objects.all().delete()
            Equipment.objects.all().delete()
            Zone.objects.all().delete()
            User.objects.filter(username__in=["admin", "aida", "bakyt", "emil"]).delete()
        if Booking.objects.exists():
            self.stdout.write("Данные уже есть. Используйте --reset, чтобы пересоздать.")
            return

        cfg = ClubSettings.get()
        cfg.opening_time, cfg.closing_time = time(10, 0), time(23, 0)
        cfg.save()

        std, vip = Zone.objects.get_or_create(name="Стандарт")[0], Zone.objects.get_or_create(name="VIP")[0]
        spec_std = "Intel Core i5, 16 ГБ RAM, RTX 3060, монитор 165 Гц"
        spec_vip = "Intel Core i7, 32 ГБ RAM, RTX 4070, монитор 240 Гц, кресло"
        devices = [
            (std, "PC Стандарт 1", "pc", spec_std, 150), (std, "PC Стандарт 2", "pc", spec_std, 150),
            (std, "PC Стандарт 3", "pc", spec_std, 150), (std, "PlayStation 5 №1", "console", "PS5, 2 геймпада, 4K-телевизор 55\"", 250),
            (vip, "PC VIP 1", "pc", spec_vip, 250), (vip, "PC VIP 2", "pc", spec_vip, 250),
            (vip, "Xbox Series X", "console", "Xbox Series X, 2 геймпада, 4K-телевизор 65\"", 300),
            (vip, "PlayStation 5 VIP", "console", "PS5, VR-комплект, проектор", 350),
        ]
        eq = [Equipment.objects.create(zone=z, name=n, kind=k, specs=sp, hourly_rate=Decimal(r)) for z, n, k, sp, r in devices]

        admin = User.objects.create_user("admin", "admin@gametime.test", "admin12345", first_name="Админ", role=User.Role.ADMIN)
        admin.is_staff = admin.is_superuser = True
        admin.save()
        clients = [User.objects.create_user(u, f"{u}@gametime.test", "client12345", first_name=n)
                   for u, n in (("aida", "Аида"), ("bakyt", "Бакыт"), ("emil", "Эмиль"))]

        tz, today = cfg.tz, timezone.now().astimezone(cfg.tz).date()

        def at(offset, hour, minute=0):
            return datetime.combine(today + timedelta(days=offset), time(hour, minute), tzinfo=tz)

        # (устройство, смещение дней, час начала, часов, статус, клиент)
        plan = [
            (0, -2, 12, 2, S.FINISHED, 0), (1, -2, 14, 1, S.FINISHED, 1), (4, -2, 18, 3, S.FINISHED, 2),
            (3, -1, 11, 2, S.FINISHED, 0), (5, -1, 15, 2, S.FINISHED, 1), (6, -1, 19, 1, S.FINISHED, 2),
            (2, -1, 13, 1, S.NO_SHOW, 1), (7, -1, 20, 2, S.NO_SHOW, 0),
            (0, 1, 12, 2, S.CANCELLED, 2), (4, 1, 16, 1, S.CANCELLED, 1),
            (0, 1, 14, 1, S.CONFIRMED, 0), (3, 1, 18, 2, S.CONFIRMED, 1), (5, 2, 17, 2, S.CONFIRMED, 2),
            (6, 3, 20, 1, S.CONFIRMED, 0),
        ]
        rows = [(eq[i], at(d, h), at(d, h) + timedelta(hours=n), st, clients[c]) for i, d, h, n, st, c in plan]
        # Идущий сеанс — начался полчаса назад
        now = timezone.now().astimezone(tz)
        started = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0) - timedelta(minutes=30)
        rows.append((eq[1], started, started + timedelta(hours=1), S.IN_PROGRESS, clients[2]))

        for e, start, end, status, user in rows:
            Booking.objects.create(user=user, equipment=e, start_at=start, end_at=end, status=status,
                                   rate_snapshot=e.hourly_rate, total_price=calc_price(e.hourly_rate, start, end))
        self.stdout.write(self.style.SUCCESS(
            "Готово. Аккаунты: admin / admin12345, aida|bakyt|emil / client12345."))

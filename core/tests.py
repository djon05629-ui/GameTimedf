from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Booking, ClubSettings, Equipment, User, Zone
from .services import BookingError


class BaseCase(TestCase):
    def setUp(self):
        self.cfg = ClubSettings.get()
        self.zone = Zone.objects.create(name="Тест")
        self.pc = Equipment.objects.create(zone=self.zone, name="PC 1", kind="pc", hourly_rate=Decimal("200"))
        self.client_user = User.objects.create_user("c1", "c1@t.test", "pass12345")
        self.other = User.objects.create_user("c2", "c2@t.test", "pass12345")
        self.admin = User.objects.create_user("adm", "adm@t.test", "pass12345", role=User.Role.ADMIN)
        self.day = timezone.now().astimezone(self.cfg.tz).date() + timedelta(days=2)

    def interval(self, h1, m1, h2, m2):
        from datetime import time
        return (services.combine(self.cfg, self.day, time(h1, m1)), services.combine(self.cfg, self.day, time(h2, m2)))

    def book(self, user, h1=14, m1=0, h2=15, m2=0):
        return services.create_booking(user, self.pc.pk, *self.interval(h1, m1, h2, m2))


class OverlapTests(BaseCase):
    def test_overlap_rejected_and_adjacent_allowed(self):
        self.book(self.client_user)
        with self.assertRaises(BookingError) as ctx:
            self.book(self.other, 14, 30, 15, 30)
        self.assertEqual(ctx.exception.status, 409)
        self.book(self.other, 15, 0, 16, 0)       # соседний интервал разрешён
        self.book(self.other, 13, 0, 14, 0)       # и слева тоже
        self.assertEqual(Booking.objects.count(), 3)

    def test_cancel_frees_interval(self):
        b = self.book(self.client_user)
        services.change_status(self.client_user, b.pk, "cancel")
        self.book(self.other, 14, 30, 15, 30)

    def test_validation_rules(self):
        for args in [(15, 0, 14, 0), (14, 0, 14, 0), (9, 0, 10, 30), (21, 30, 22, 30)]:
            with self.assertRaises(BookingError) as ctx:
                self.book(self.client_user, *args)
            self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(BookingError):
            self.book(self.client_user, 14, 10, 15, 0)   # не по шагу 30 минут
        past = timezone.now() - timedelta(hours=2)
        with self.assertRaises(BookingError):
            services.create_booking(self.client_user, self.pc.pk, past, past + timedelta(hours=1))

    def test_inactive_equipment(self):
        self.pc.is_active = False
        self.pc.save()
        with self.assertRaises(BookingError):
            self.book(self.client_user)


class PriceTests(BaseCase):
    def test_price_and_snapshot(self):
        b = self.book(self.client_user, 14, 0, 15, 30)
        self.assertEqual(b.total_price, Decimal("300.00"))
        self.pc.hourly_rate = Decimal("500")
        self.pc.save()
        b.refresh_from_db()
        self.assertEqual((b.rate_snapshot, b.total_price), (Decimal("200.00"), Decimal("300.00")))


class StatusTests(BaseCase):
    def started_booking(self, status=Booking.Status.CONFIRMED):
        start = timezone.now() - timedelta(minutes=10)
        return Booking.objects.create(user=self.client_user, equipment=self.pc, start_at=start,
                                      end_at=start + timedelta(hours=1), status=status,
                                      rate_snapshot=200, total_price=200)

    def test_client_cannot_cancel_foreign_or_finish(self):
        b = self.book(self.client_user)
        with self.assertRaises(PermissionDenied):
            services.change_status(self.other, b.pk, "cancel")
        with self.assertRaises(PermissionDenied):
            services.change_status(self.client_user, b.pk, "finish")

    def test_flow_and_forbidden_transitions(self):
        b = self.started_booking()
        with self.assertRaises(BookingError):     # отмена после начала запрещена
            services.change_status(self.client_user, b.pk, "cancel")
        with self.assertRaises(BookingError):     # завершить, не начав
            services.change_status(self.admin, b.pk, "finish")
        services.change_status(self.admin, b.pk, "start")
        services.change_status(self.admin, b.pk, "finish")
        with self.assertRaises(BookingError):     # завершённую менять нельзя
            services.change_status(self.admin, b.pk, "no_show")

    def test_no_show_only_after_start(self):
        future = self.book(self.client_user)
        with self.assertRaises(BookingError):
            services.change_status(self.admin, future.pk, "no_show")
        started = self.started_booking()
        self.assertEqual(services.change_status(self.admin, started.pk, "no_show").status, Booking.Status.NO_SHOW)


class ViewTests(BaseCase):
    def test_pages_open(self):
        for name in ("home", "catalog"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("equipment_detail", args=[self.pc.pk])).status_code, 200)

    def test_slots_api(self):
        r = self.client.get(reverse("equipment_slots", args=[self.pc.pk]), {"date": self.day.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(s["state"] == "free" for s in r.json()["slots"]))
        self.assertEqual(self.client.get(reverse("equipment_slots", args=[self.pc.pk])).status_code, 400)

    def test_panel_permissions(self):
        self.assertEqual(self.client.get(reverse("panel")).status_code, 302)       # аноним -> вход
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("panel")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("panel")).status_code, 200)
        self.assertEqual(self.client.get(reverse("utilization")).status_code, 200)

    def test_create_booking_via_form_and_foreign_cancel(self):
        self.client.force_login(self.client_user)
        r = self.client.post(reverse("booking_create"), {
            "equipment": self.pc.pk, "date": self.day.isoformat(), "start": "14:00", "end": "15:00"})
        self.assertRedirects(r, reverse("my_bookings"))
        b = Booking.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("booking_cancel", args=[b.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("booking_finish", args=[b.pk])).status_code, 403)

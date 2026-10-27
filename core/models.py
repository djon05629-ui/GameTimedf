from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        ADMIN = "admin", "Администратор"

    email = models.EmailField("Email", unique=True)
    role = models.CharField("Роль", max_length=10, choices=Role.choices, default=Role.CLIENT)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_club_admin(self):
        return self.role == self.Role.ADMIN


class Zone(models.Model):
    name = models.CharField("Название", max_length=60, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "зона"
        verbose_name_plural = "зоны"

    def __str__(self):
        return self.name


class Equipment(models.Model):
    class Kind(models.TextChoices):
        PC = "pc", "Компьютер"
        CONSOLE = "console", "Консоль"

    zone = models.ForeignKey(Zone, verbose_name="Зона", on_delete=models.PROTECT, related_name="equipment")
    name = models.CharField("Название", max_length=80)
    kind = models.CharField("Тип", max_length=10, choices=Kind.choices)
    specs = models.TextField("Характеристики", blank=True)
    hourly_rate = models.DecimalField(
        "Стоимость часа, сом", max_digits=8, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    is_active = models.BooleanField("Доступно для брони", default=True)

    class Meta:
        ordering = ["zone__name", "name"]
        verbose_name = "оборудование"
        verbose_name_plural = "оборудование"
        indexes = [models.Index(fields=["kind", "is_active"])]
        constraints = [models.UniqueConstraint(fields=["zone", "name"], name="uniq_equipment_name_in_zone")]

    def __str__(self):
        return self.name


class ClubSettings(models.Model):
    opening_time = models.TimeField("Открытие", default=time(10, 0))
    closing_time = models.TimeField("Закрытие", default=time(22, 0))
    timezone = models.CharField("Часовой пояс", max_length=64, default="Asia/Bishkek")

    class Meta:
        verbose_name = "настройки клуба"
        verbose_name_plural = "настройки клуба"

    def __str__(self):
        return "Настройки клуба"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def tz(self):
        return ZoneInfo(self.timezone)

    def clean(self):
        errors = {}
        if self.opening_time and self.closing_time:
            if self.opening_time >= self.closing_time:
                errors["closing_time"] = "Закрытие должно быть позже открытия: переход через полночь не поддерживается."
            for field in ("opening_time", "closing_time"):
                value = getattr(self, field)
                if value.minute % 30 or value.second:
                    errors[field] = "Время должно быть кратно 30 минутам."
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = "Неизвестный часовой пояс. Пример: Asia/Bishkek."
        if errors:
            raise ValidationError(errors)


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Подтверждена"
        IN_PROGRESS = "in_progress", "Идёт"
        FINISHED = "finished", "Завершена"
        CANCELLED = "cancelled", "Отменена"
        NO_SHOW = "no_show", "Неявка"

    ACTIVE = (Status.CONFIRMED, Status.IN_PROGRESS)

    user = models.ForeignKey(User, verbose_name="Клиент", on_delete=models.PROTECT, related_name="bookings")
    equipment = models.ForeignKey(Equipment, verbose_name="Устройство", on_delete=models.PROTECT, related_name="bookings")
    start_at = models.DateTimeField("Начало")
    end_at = models.DateTimeField("Конец")
    status = models.CharField("Статус", max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    rate_snapshot = models.DecimalField("Тариф на момент брони", max_digits=8, decimal_places=2)
    total_price = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_at"]
        verbose_name = "бронь"
        verbose_name_plural = "брони"
        indexes = [
            models.Index(fields=["equipment", "start_at", "end_at"]),
            models.Index(fields=["status", "start_at"]),
            models.Index(fields=["user", "start_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_at__gt=models.F("start_at")), name="booking_end_after_start"),
            models.CheckConstraint(condition=models.Q(total_price__gte=0), name="booking_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.equipment} {self.start_at:%d.%m %H:%M}"

    @property
    def hours(self):
        return Decimal((self.end_at - self.start_at).total_seconds()) / Decimal(3600)

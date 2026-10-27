"""Бизнес-логика бронирования. Все проверки — на сервере."""
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Booking, ClubSettings, Equipment

STEP_MINUTES = 30
MIN_MINUTES = 30


class BookingError(Exception):
    """Ошибка бизнес-правила. status — HTTP-эквивалент (400/403/404/409)."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def calc_price(rate, start, end):
    minutes = Decimal((end - start).total_seconds()) / Decimal(60)
    return (Decimal(rate) * minutes / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def combine(cfg, day, t):
    return datetime.combine(day, t, tzinfo=cfg.tz)


def day_window(cfg, day):
    return combine(cfg, day, cfg.opening_time), combine(cfg, day, cfg.closing_time)


def active_bookings(equipment_ids, window_start, window_end):
    return Booking.objects.filter(
        equipment_id__in=equipment_ids,
        status__in=Booking.ACTIVE,
        start_at__lt=window_end,
        end_at__gt=window_start,
    )


def build_slots(cfg, day, busy, now=None):
    """Слоты по 30 минут. busy — список броней (start_at/end_at). Состояния: free / busy / past."""
    now = now or timezone.now()
    opening, closing = day_window(cfg, day)
    slots, cur = [], opening
    while cur + timedelta(minutes=STEP_MINUTES) <= closing:
        nxt = cur + timedelta(minutes=STEP_MINUTES)
        if any(b.start_at < nxt and b.end_at > cur for b in busy):
            state = "busy"
        elif cur <= now:
            state = "past"
        else:
            state = "free"
        slots.append({"start": cur.astimezone(cfg.tz).strftime("%H:%M"),
                      "end": nxt.astimezone(cfg.tz).strftime("%H:%M"), "state": state})
        cur = nxt
    return slots


def equipment_slots(equipment, day, cfg=None):
    cfg = cfg or ClubSettings.get()
    opening, closing = day_window(cfg, day)
    busy = list(active_bookings([equipment.pk], opening, closing))
    return build_slots(cfg, day, busy)


def parse_interval(cfg, day_str, start_str, end_str):
    try:
        day = date.fromisoformat(day_str)
        start = combine(cfg, day, datetime.strptime(start_str, "%H:%M").time())
        end = combine(cfg, day, datetime.strptime(end_str, "%H:%M").time())
    except (TypeError, ValueError):
        raise BookingError("Укажите дату и время в формате ГГГГ-ММ-ДД и ЧЧ:ММ.", 400)
    return start, end


def _validate_interval(cfg, start, end):
    now = timezone.now()
    if end <= start:
        raise BookingError("Конец брони должен быть позже начала.", 400)
    if (end - start) < timedelta(minutes=MIN_MINUTES):
        raise BookingError("Минимальная длительность брони — 30 минут.", 400)
    for moment in (start, end):
        if moment.minute % STEP_MINUTES or moment.second:
            raise BookingError("Время брони выбирается с шагом 30 минут.", 400)
    if start <= now:
        raise BookingError("Начало брони должно быть в будущем.", 400)
    local_start, local_end = start.astimezone(cfg.tz), end.astimezone(cfg.tz)
    if local_start.date() != local_end.date() or local_start.time() < cfg.opening_time or local_end.time() > cfg.closing_time:
        raise BookingError(
            f"Клуб работает с {cfg.opening_time:%H:%M} до {cfg.closing_time:%H:%M}. Выберите время в этом интервале.", 400)


@transaction.atomic
def create_booking(user, equipment_id, start, end):
    """Проверка занятости и запись — атомарно, с блокировкой строки устройства."""
    cfg = ClubSettings.get()
    equipment = Equipment.objects.select_for_update().filter(pk=equipment_id).first()
    if equipment is None:
        raise BookingError("Устройство не найдено.", 404)
    if not equipment.is_active:
        raise BookingError("Это устройство сейчас отключено и недоступно для брони.", 409)
    _validate_interval(cfg, start, end)
    overlap = Booking.objects.filter(
        equipment=equipment, status__in=Booking.ACTIVE, start_at__lt=end, end_at__gt=start
    ).exists()
    if overlap:
        raise BookingError("Это время уже занято. Выберите другой интервал.", 409)
    return Booking.objects.create(
        user=user, equipment=equipment, start_at=start, end_at=end,
        status=Booking.Status.CONFIRMED,
        rate_snapshot=equipment.hourly_rate,
        total_price=calc_price(equipment.hourly_rate, start, end),
    )


@transaction.atomic
def change_status(actor, booking_id, action):
    """action: cancel | start | finish | no_show. Возвращает обновлённую бронь."""
    booking = Booking.objects.select_for_update().filter(pk=booking_id).first()
    if booking is None:
        raise BookingError("Бронь не найдена.", 404)
    S, now = Booking.Status, timezone.now()

    if action == "cancel":
        if booking.user_id != actor.pk and not actor.is_club_admin:
            raise PermissionDenied
        if booking.status != S.CONFIRMED:
            raise BookingError("Отменить можно только подтверждённую бронь.", 409)
        if now >= booking.start_at:
            raise BookingError("Бронь уже началась — отменить её нельзя.", 409)
        booking.status = S.CANCELLED
    else:
        if not actor.is_club_admin:
            raise PermissionDenied
        if action == "start":
            if booking.status != S.CONFIRMED:
                raise BookingError("Начать можно только подтверждённую бронь.", 409)
            if now < booking.start_at:
                raise BookingError("Сеанс ещё не должен начаться — дождитесь времени брони.", 409)
            booking.status = S.IN_PROGRESS
        elif action == "finish":
            if booking.status != S.IN_PROGRESS:
                raise BookingError("Завершить можно только идущий сеанс.", 409)
            booking.status = S.FINISHED
        elif action == "no_show":
            if booking.status != S.CONFIRMED:
                raise BookingError("Неявку можно отметить только у подтверждённой брони.", 409)
            if now < booking.start_at:
                raise BookingError("Неявку можно отметить только после начала брони.", 409)
            booking.status = S.NO_SHOW
        else:
            raise BookingError("Неизвестное действие.", 400)
    booking.save(update_fields=["status"])
    return booking


def utilization_report(date_from, date_to, cfg=None):
    """Занятые часы и выручка с завершённых сеансов за период [date_from, date_to]."""
    cfg = cfg or ClubSettings.get()
    start = combine(cfg, date_from, time(0, 0))
    end = combine(cfg, date_to + timedelta(days=1), time(0, 0))
    S = Booking.Status
    qs = Booking.objects.filter(start_at__gte=start, start_at__lt=end).select_related("equipment")
    rows, total_hours, revenue, finished = {}, Decimal(0), Decimal(0), 0
    for b in qs:
        if b.status in (S.CANCELLED, S.NO_SHOW):
            continue
        row = rows.setdefault(b.equipment_id, {"equipment": b.equipment, "hours": Decimal(0), "revenue": Decimal(0)})
        row["hours"] += b.hours
        total_hours += b.hours
        if b.status == S.FINISHED:
            row["revenue"] += b.total_price
            revenue += b.total_price
            finished += 1
    return {"rows": sorted(rows.values(), key=lambda r: -r["hours"]),
            "hours": total_hours, "revenue": revenue, "finished": finished}

from collections import defaultdict
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import services
from .forms import (ClubSettingsForm, DateRangeForm, EquipmentForm, ProfileForm,
                    RegisterForm, ZoneForm)
from .models import Booking, ClubSettings, Equipment, User, Zone
from .services import BookingError


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_club_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return login_required(wrapper)


def parse_date(value, default=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def today_in_club(cfg):
    return timezone.now().astimezone(cfg.tz).date()


def paginate(request, qs, per_page=8):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def error_403(request, exception=None):
    return render(request, "403.html", status=403)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


# ---------- Публичные страницы ----------

def home(request):
    cfg = ClubSettings.get()
    featured = Equipment.objects.filter(is_active=True).select_related("zone")[:4]
    return render(request, "home.html", {
        "cfg": cfg, "featured": featured,
        "total": Equipment.objects.filter(is_active=True).count(),
    })


def catalog(request):
    cfg = ClubSettings.get()
    day = parse_date(request.GET.get("date"), today_in_club(cfg))
    kind = request.GET.get("kind", "")
    zone = request.GET.get("zone", "")
    qs = Equipment.objects.filter(is_active=True).select_related("zone")
    if kind in Equipment.Kind.values:
        qs = qs.filter(kind=kind)
    if zone.isdigit():
        qs = qs.filter(zone_id=zone)
    page = paginate(request, qs, 6)

    opening, closing = services.day_window(cfg, day)
    busy = defaultdict(list)
    for b in services.active_bookings([e.pk for e in page], opening, closing):
        busy[b.equipment_id].append(b)
    for e in page:
        slots = services.build_slots(cfg, day, busy[e.pk])
        e.free_count = sum(1 for s in slots if s["state"] == "free")
        e.total_slots = len(slots)

    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "catalog.html", {
        "page": page, "day": day, "kind": kind, "zone": zone, "zones": Zone.objects.all(),
        "kinds": Equipment.Kind.choices, "querystring": query.urlencode(),
    })


def equipment_detail(request, pk):
    cfg = ClubSettings.get()
    equipment = get_object_or_404(Equipment.objects.select_related("zone"), pk=pk)
    day = parse_date(request.GET.get("date"), today_in_club(cfg))
    return render(request, "equipment_detail.html", {"e": equipment, "day": day, "cfg": cfg})


@require_GET
def equipment_slots_api(request, pk):
    cfg = ClubSettings.get()
    equipment = get_object_or_404(Equipment, pk=pk)
    day = parse_date(request.GET.get("date"))
    if day is None:
        return JsonResponse({"error": "Укажите дату в формате ГГГГ-ММ-ДД."}, status=400)
    return JsonResponse({
        "date": day.isoformat(), "rate": str(equipment.hourly_rate), "active": equipment.is_active,
        "open": f"{cfg.opening_time:%H:%M}", "close": f"{cfg.closing_time:%H:%M}",
        "slots": services.equipment_slots(equipment, day, cfg) if equipment.is_active else [],
    })


# ---------- Брони клиента ----------

@login_required
@require_POST
def create_booking_view(request):
    cfg = ClubSettings.get()
    equipment_id = request.POST.get("equipment", "")
    day_str = request.POST.get("date", "")
    back = reverse("equipment_detail", args=[equipment_id]) if equipment_id.isdigit() else reverse("catalog")
    try:
        start, end = services.parse_interval(cfg, day_str, request.POST.get("start"), request.POST.get("end"))
        booking = services.create_booking(request.user, equipment_id, start, end)
    except BookingError as exc:
        messages.error(request, exc.message)
        return redirect(f"{back}?date={day_str}")
    messages.success(request, f"Бронь подтверждена: {booking.equipment.name}, {start:%d.%m %H:%M}–{end:%H:%M}, "
                              f"{booking.total_price:.2f} сом.")
    return redirect("my_bookings")


@login_required
def my_bookings(request):
    tab = request.GET.get("tab", "upcoming")
    qs = Booking.objects.filter(user=request.user).select_related("equipment__zone")
    if tab == "history":
        qs = qs.exclude(status__in=Booking.ACTIVE).order_by("-start_at")
    else:
        tab = "upcoming"
        qs = qs.filter(status__in=Booking.ACTIVE).order_by("start_at")
    return render(request, "my_bookings.html", {"page": paginate(request, qs), "tab": tab, "now": timezone.now()})


@login_required
@require_POST
def booking_action(request, pk, action):
    try:
        booking = services.change_status(request.user, pk, action)
        messages.success(request, {
            "cancel": "Бронь отменена. Интервал снова свободен.",
            "start": "Сеанс начат.", "finish": "Сеанс завершён.", "no_show": "Отмечена неявка.",
        }[action])
    except BookingError as exc:
        if exc.status == 404:
            raise Http404(exc.message)
        messages.error(request, exc.message)
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("my_bookings")


# ---------- Панель клуба ----------

@admin_required
def panel(request):
    cfg = ClubSettings.get()
    day = parse_date(request.GET.get("date"), today_in_club(cfg))
    status = request.GET.get("status", "")
    opening, closing = services.day_window(cfg, day)
    day_qs = Booking.objects.filter(start_at__gte=opening.replace(hour=0, minute=0),
                                    start_at__lt=opening.replace(hour=0, minute=0) + timedelta(days=1)
                                    ).select_related("equipment", "user")
    # Календарь дня: полосы броней на шкале рабочего времени
    span = (closing - opening).total_seconds()
    lanes = []
    for e in Equipment.objects.select_related("zone"):
        bars = []
        for b in day_qs:
            if b.equipment_id == e.pk and b.status not in (Booking.Status.CANCELLED, Booking.Status.NO_SHOW):
                left = max(0, (b.start_at - opening).total_seconds() / span * 100)
                right = min(100, (b.end_at - opening).total_seconds() / span * 100)
                if right > left:
                    bars.append({"b": b, "left": round(left, 2), "width": round(right - left, 2)})
        lanes.append({"e": e, "bars": bars})
    hours = []
    h = opening
    while h <= closing:
        hours.append({"label": f"{h.astimezone(cfg.tz):%H:%M}", "left": round((h - opening).total_seconds() / span * 100, 2)})
        h += timedelta(hours=1)

    rows = day_qs
    if status in Booking.Status.values:
        rows = rows.filter(status=status)
    return render(request, "panel.html", {
        "cfg": cfg, "day": day, "prev": day - timedelta(days=1), "next": day + timedelta(days=1),
        "status": status, "statuses": Booking.Status.choices, "lanes": lanes, "hours": hours,
        "bookings": rows.order_by("start_at"), "now": timezone.now(),
    })


@admin_required
def utilization(request):
    cfg = ClubSettings.get()
    today = today_in_club(cfg)
    initial = {"date_from": today - timedelta(days=6), "date_to": today}
    form = DateRangeForm(request.GET or initial)
    report = None
    if form.is_valid():
        report = services.utilization_report(form.cleaned_data["date_from"], form.cleaned_data["date_to"], cfg)
    return render(request, "utilization.html", {"form": form, "report": report})


# ---------- Оборудование, настройки, пользователи ----------

@admin_required
def manage_equipment(request):
    qs = Equipment.objects.select_related("zone")
    return render(request, "manage_equipment.html", {"page": paginate(request, qs, 10), "zone_form": ZoneForm()})


@admin_required
def equipment_edit(request, pk=None):
    instance = get_object_or_404(Equipment, pk=pk) if pk else None
    form = EquipmentForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Оборудование сохранено. Уже созданные брони сохраняют свой тариф.")
        return redirect("manage_equipment")
    return render(request, "equipment_form.html", {"form": form, "instance": instance})


@admin_required
@require_POST
def zone_create(request):
    form = ZoneForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Зона добавлена.")
    else:
        messages.error(request, "Не удалось добавить зону: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("manage_equipment")


@admin_required
def club_settings(request):
    form = ClubSettingsForm(request.POST or None, instance=ClubSettings.get())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Настройки клуба сохранены.")
        return redirect("club_settings")
    return render(request, "settings_form.html", {"form": form})


@admin_required
def manage_users(request):
    if request.method == "POST":
        user = get_object_or_404(User, pk=request.POST.get("user"))
        role = request.POST.get("role")
        if role not in User.Role.values:
            messages.error(request, "Неизвестная роль.")
        elif user == request.user:
            messages.error(request, "Нельзя менять роль самому себе — так вы не потеряете доступ случайно.")
        else:
            user.role = role
            user.save(update_fields=["role"])
            messages.success(request, f"Роль пользователя {user.username} изменена: {user.get_role_display()}.")
        return redirect("manage_users")
    return render(request, "manage_users.html", {"page": paginate(request, User.objects.order_by("username"), 10),
                                                  "roles": User.Role.choices})


# ---------- Аккаунты ----------

def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()  # роль по умолчанию — клиент; служебные роли назначает только администратор
        login(request, user)
        messages.success(request, "Аккаунт создан. Выберите устройство и забронируйте время.")
        return redirect("catalog")
    return render(request, "registration/register.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль сохранён.")
        return redirect("profile")
    return render(request, "registration/profile.html", {"form": form})

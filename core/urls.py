from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("equipment/", views.catalog, name="catalog"),
    path("equipment/<int:pk>/", views.equipment_detail, name="equipment_detail"),
    path("equipment/<int:pk>/slots", views.equipment_slots_api, name="equipment_slots"),
    path("bookings/", views.create_booking_view, name="booking_create"),
    path("bookings/mine/", views.my_bookings, name="my_bookings"),
    path("bookings/<int:pk>/cancel", views.booking_action, {"action": "cancel"}, name="booking_cancel"),
    path("bookings/<int:pk>/start", views.booking_action, {"action": "start"}, name="booking_start"),
    path("bookings/<int:pk>/finish", views.booking_action, {"action": "finish"}, name="booking_finish"),
    path("bookings/<int:pk>/no-show", views.booking_action, {"action": "no_show"}, name="booking_no_show"),
    path("club/", views.panel, name="panel"),
    path("reports/utilization", views.utilization, name="utilization"),
    path("manage/equipment/", views.manage_equipment, name="manage_equipment"),
    path("manage/equipment/new/", views.equipment_edit, name="equipment_new"),
    path("manage/equipment/<int:pk>/edit/", views.equipment_edit, name="equipment_edit"),
    path("manage/zones/new/", views.zone_create, name="zone_create"),
    path("manage/settings/", views.club_settings, name="club_settings"),
    path("manage/users/", views.manage_users, name="manage_users"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/profile/", views.profile, name="profile"),
]

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Booking, ClubSettings, Equipment, User, Zone

admin.site.register(User, UserAdmin)
admin.site.register(Zone)
admin.site.register(Equipment)
admin.site.register(ClubSettings)
admin.site.register(Booking)

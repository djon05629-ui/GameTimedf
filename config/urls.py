from django.contrib import admin
from django.urls import include, path

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

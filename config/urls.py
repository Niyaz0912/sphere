from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core import views as core_views

admin.site.site_header = "Сфера"
admin.site.site_title = "Сфера"
admin.site.index_title = "Управление сервисом"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/register/", core_views.register, name="register"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", core_views.home, name="home"),
    path("s/<slug:slug>/", core_views.public_master, name="public_master"),
    path(
        "m/<slug:slug>/",
        RedirectView.as_view(pattern_name="public_master", permanent=True),
        name="public_master_legacy",
    ),
    path("clients/", include("core.urls")),
    path("settings/", core_views.settings_view, name="settings"),
    path("", include("shop.urls")),
]

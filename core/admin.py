from django.contrib import admin

from .models import Client, MasterProfile


@admin.register(MasterProfile)
class MasterProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "slug", "theme", "is_public", "phone", "user")
    search_fields = ("business_name", "slug", "user__username", "phone")
    list_filter = ("theme", "is_public")
    list_editable = ("is_public",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "identifier", "owner", "created_at")
    search_fields = ("name", "phone", "identifier", "owner__username")
    list_filter = ("owner",)
    raw_id_fields = ("owner",)

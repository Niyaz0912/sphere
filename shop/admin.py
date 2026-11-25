from django.contrib import admin

from .models import Order, PipelineStage, PromoOffer, Service, ServicePhoto


@admin.register(ServicePhoto)
class ServicePhotoAdmin(admin.ModelAdmin):
    list_display = ("service", "caption", "order", "created_at")
    list_filter = ("service__owner",)
    search_fields = ("caption", "service__name")
    ordering = ("service", "order", "id")
@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "order", "color", "is_final")
    list_filter = ("owner", "color", "is_final")
    search_fields = ("name", "owner__username")
    ordering = ("owner", "order", "id")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "price",
        "old_price",
        "cost_price",
        "duration_minutes",
        "is_active",
    )
    list_filter = ("owner", "is_active")
    search_fields = ("name", "owner__username")
    list_editable = ("price", "old_price", "cost_price", "is_active")


@admin.register(PromoOffer)
class PromoOfferAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "badge_text",
        "is_featured",
        "is_active",
        "expires_at",
        "clicks_count",
    )
    list_filter = ("owner", "is_active", "is_featured")
    search_fields = ("title", "description", "promo_code", "owner__username")
    readonly_fields = ("clicks_count", "created_at")
    date_hierarchy = "expires_at"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "scheduled_at",
        "client",
        "service_name",
        "stage",
        "total_amount",
        "paid_amount",
        "payment_method",
        "owner",
    )
    list_filter = ("owner", "stage", "payment_method")
    search_fields = ("client__name", "client__phone", "service_name", "work_details")
    date_hierarchy = "scheduled_at"
    raw_id_fields = ("client", "service", "stage")
    readonly_fields = ("created_at", "updated_at")

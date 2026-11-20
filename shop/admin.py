from django.contrib import admin

from .models import Order, PipelineStage, Service


@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "order", "color", "is_final")
    list_filter = ("owner", "color", "is_final")
    search_fields = ("name", "owner__username")
    ordering = ("owner", "order", "id")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "price", "cost_price", "duration_minutes", "is_active")
    list_filter = ("owner", "is_active")
    search_fields = ("name", "owner__username")
    list_editable = ("price", "cost_price", "is_active")


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

from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/pay/", views.order_pay, name="order_pay"),
    path("orders/<int:pk>/advance/", views.order_advance, name="order_advance"),
    path("services/", views.service_list, name="services"),
    path("services/save/", views.service_save, name="service_save"),
    path("services/<int:pk>/delete/", views.service_delete, name="service_delete"),
    path("services/export/", views.service_export, name="service_export"),
    path("services/template/", views.service_template, name="service_template"),
    path("services/import/", views.service_import, name="service_import"),
    path("analytics/", views.analytics, name="analytics"),
]

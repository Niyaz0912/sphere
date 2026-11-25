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
    path(
        "services/<int:pk>/photos/upload/",
        views.service_photo_upload,
        name="service_photo_upload",
    ),
    path(
        "services/photos/<int:pk>/caption/",
        views.service_photo_caption,
        name="service_photo_caption",
    ),
    path(
        "services/photos/<int:pk>/delete/",
        views.service_photo_delete,
        name="service_photo_delete",
    ),
    path("services/export/", views.service_export, name="service_export"),
    path("services/template/", views.service_template, name="service_template"),
    path("services/import/", views.service_import, name="service_import"),
    path("promos/", views.promo_list, name="promos"),
    path("promos/save/", views.promo_save, name="promo_save"),
    path("promos/<int:pk>/toggle/", views.promo_toggle, name="promo_toggle"),
    path("promos/<int:pk>/delete/", views.promo_delete, name="promo_delete"),
    path("promo/<int:pk>/go/", views.promo_go, name="promo_go"),
    path("analytics/", views.analytics, name="analytics"),
]

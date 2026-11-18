from django.urls import path

from apps.google_services.views import SyncEmailsView


app_name = "google_services_v1"

urlpatterns = [
    path("sync/", SyncEmailsView.as_view(), name="gmail_sync"),
]

from django.urls import path

from apps.google_services.views import (
    DashboardStatsView,
    DisconnectGmailView,
    EmailDetailView,
    EmailListView,
    GmailLabelsView,
    OAuthCallbackView,
    OAuthInitiateView,
    SyncEmailsView,
)


app_name = "google_services"

urlpatterns = [
    path('oauth/initiate/', OAuthInitiateView.as_view(), name='gmail_oauth_initiate'),
    path('oauth/callback/', OAuthCallbackView.as_view(), name='gmail_oauth_callback'),
    path('disconnect/', DisconnectGmailView.as_view(), name='gmail_disconnect'),

    path("labels/",GmailLabelsView.as_view(),name="gmail_labels",),
    path("sync/",SyncEmailsView.as_view(),name="gmail_sync",),

    path("", EmailListView.as_view(), name="email_list"),
    path("<int:pk>/", EmailDetailView.as_view(), name="email_detail"),

    path("stats/",DashboardStatsView.as_view(),name="dashboard_stats",),
    
]

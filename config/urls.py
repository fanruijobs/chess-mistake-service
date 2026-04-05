from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def root_redirect(_request):
    return redirect("mistakes:player-list")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", root_redirect),
    path("", include(("mistakes.urls", "mistakes"), namespace="mistakes")),
]

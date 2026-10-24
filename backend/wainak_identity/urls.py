from django.urls import include, path, re_path
from .views import dispatch

urlpatterns = [path("_allauth/", include("allauth.headless.urls")),
               re_path(r"^(?:identity/v1|v1)/.*$", dispatch)]

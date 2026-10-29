from django.urls import include, path, re_path
from .views import dispatch
from .web_deletion import page

urlpatterns = [re_path(r"^account-deletion/?$", page), path("_allauth/", include("allauth.headless.urls")),
               re_path(r"^(?:identity/v1|v1)/.*$", dispatch)]

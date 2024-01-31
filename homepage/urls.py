from django.urls import path
from . import views

app_name = "homepage"

urlpatterns = [
    path("", views.index, name="index"),
    path('save-document', views.save_doc, name='save_doc')
]
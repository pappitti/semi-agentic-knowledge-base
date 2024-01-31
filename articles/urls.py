from django.urls import path
from . import views

app_name = "articles"

urlpatterns = [
    path('<slug:document_slug>', views.document_details, name='document_details'),
    path('<slug:document_slug>/edit', views.edit_document_details, name='edit_document_details'),
    path('<slug:document_slug>/delete', views.delete_document, name='delete_document')
    ]
from django.urls import path
from . import views

app_name = "newdocs"

urlpatterns = [
    path('', views.new_docs, name='new_docs'),
    path('add', views.add_new_docs, name='add_new_docs'),
    path('add/launch', views.launch_processing, name='launch_processing'),
    path('<slug:document_slug>/resubmit', views.resubmit_document, name='resubmit_document'),
    path('manual', views.manual, name='manual'),
    path('progress-update/<str:task_id>/', views.progress_update, name='progress_update'),
    path('process-summary', views.process_summary, name='process_summary'),
    path('process-complete', views.process_complete, name='process_complete'),
    ]
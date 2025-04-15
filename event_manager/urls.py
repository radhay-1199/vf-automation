from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    path('', views.FlightListView.as_view(), name='flight-list'),
    path('flight/new/', views.FlightCreateView.as_view(), name='flight-create'),
    path('flight/<int:pk>/', views.flight_detail, name='flight-detail'),
    path('flight/<int:pk>/add-event/', views.add_event, name='add-event'),
    path('flight/<int:pk>/import-events/', views.import_events, name='import-events'),
    path('flight/<int:pk>/delete/', views.delete_flight, name='delete-flight'),
    path('flight/<int:flight_pk>/event/<int:event_pk>/delete/', views.delete_event, name='delete-event'),
    path('flight/<int:flight_pk>/event/<int:event_pk>/edit/', views.edit_event, name='edit-event'),
    path('flight/<int:flight_pk>/event-form/', views.get_event_form, name='get-event-form'),
    path('flight/<int:flight_pk>/get-event/', views.get_event, name='get-event'),
    path('flight/<int:flight_pk>/get-event-with-fid/', views.get_event_with_fid, name='get-event-with-fid'),
    path('flight/<int:flight_pk>/delete-all-events/', views.delete_all_events, name='delete-all-events'),
    path('flight/<int:flight_id>/run-cleanup/', views.run_cleanup_query, name='run-cleanup'),
    path('produce-kafka-event/', views.produce_kafka_event, name='produce-kafka-event'),
    path('api/flight', api_views.flight_query, name='api-flight-query'),
    path('api/addflightpush', api_views.add_flight_push, name='api-flight-push'),
    path('api/transform-payload/', views.transform_payload, name='transform-payload'),
    path('api/proxy-request/', views.proxy_api_request, name='proxy-api-request'),
] 
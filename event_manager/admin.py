from django.contrib import admin
from .models import Flight, FlightEvent, MockConfiguration, AdditionalTask

@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ('flight_unique_id', 'created_at', 'updated_at')
    search_fields = ('flight_unique_id',)

@admin.register(FlightEvent)
class FlightEventAdmin(admin.ModelAdmin):
    list_display = ('flight', 'flight_state', 'priority', 'is_played')
    list_filter = ('flight', 'flight_state', 'is_played')
    search_fields = ('flight__flight_unique_id', 'flight_state')

@admin.register(MockConfiguration)
class MockConfigurationAdmin(admin.ModelAdmin):
    list_display = ('flight', 'delay_between_events', 'fast_forward', 'manual_mode')
    list_filter = ('fast_forward', 'manual_mode')

@admin.register(AdditionalTask)
class AdditionalTaskAdmin(admin.ModelAdmin):
    list_display = ('name', 'task_type', 'configuration', 'order', 'is_enabled')
    list_filter = ('task_type', 'is_enabled')
    search_fields = ('name',)

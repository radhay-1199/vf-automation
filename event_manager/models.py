from django.db import models
from django.utils import timezone

class Flight(models.Model):
    flight_unique_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.flight_unique_id

class FlightEvent(models.Model):
    flight = models.ForeignKey(Flight, on_delete=models.CASCADE, related_name='events')
    raw_event = models.TextField()  # Store the complete raw event
    flight_state = models.CharField(max_length=50)
    priority = models.IntegerField()
    identified_changes = models.TextField(blank=True)
    is_played = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', 'created_at']

    def __str__(self):
        return f"{self.flight.flight_unique_id} - {self.flight_state} - Priority: {self.priority}"

class MockConfiguration(models.Model):
    flight = models.ForeignKey(Flight, on_delete=models.CASCADE)
    delay_between_events = models.IntegerField(default=5)  # seconds
    fast_forward = models.BooleanField(default=False)
    manual_mode = models.BooleanField(default=False)
    callback_url = models.URLField()
    cleanup_before_start = models.BooleanField(default=True)
    cleanup_query = models.TextField(blank=True, help_text="SQL query to run before starting mock")
    use_custom_db = models.BooleanField(default=False, help_text="Use a custom database for cleanup query")
    db_host = models.CharField(max_length=255, blank=True, help_text="Database host")
    db_port = models.CharField(max_length=10, blank=True, help_text="Database port", default="5432")
    db_name = models.CharField(max_length=255, blank=True, help_text="Database name")
    db_user = models.CharField(max_length=255, blank=True, help_text="Database username")
    db_password = models.CharField(max_length=255, blank=True, help_text="Database password")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Config for {self.flight.flight_unique_id}"

class AdditionalTask(models.Model):
    TASK_TYPES = [
        ('kafka', 'Kafka Event'),
        ('api', 'API Call'),
        ('cleanup', 'Cleanup Task'),
    ]
    
    name = models.CharField(max_length=100)
    task_type = models.CharField(max_length=20, choices=TASK_TYPES)
    configuration = models.ForeignKey(MockConfiguration, on_delete=models.CASCADE, related_name='tasks')
    payload_template = models.TextField(help_text="JSON template for the task")
    order = models.IntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.name} ({self.task_type})"

from django import forms
from .models import Flight, FlightEvent, MockConfiguration, AdditionalTask

class FlightForm(forms.ModelForm):
    class Meta:
        model = Flight
        fields = ['flight_unique_id']

class FlightEventForm(forms.ModelForm):
    priority = forms.IntegerField(
        required=False, 
        min_value=0,
        help_text="Optional. Leave empty for next available priority, or specify a number to insert at that position."
    )
    
    class Meta:
        model = FlightEvent
        fields = ['raw_event', 'flight_state', 'priority', 'identified_changes']
        widgets = {
            'raw_event': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': '{"key": "value"}'
            }),
            'identified_changes': forms.Textarea(attrs={'rows': 3}),
        }
        
    def clean_priority(self):
        priority = self.cleaned_data.get('priority')
        return priority if priority is not None else 0

class MockConfigurationForm(forms.ModelForm):
    class Meta:
        model = MockConfiguration
        fields = [
            'delay_between_events', 'fast_forward', 'manual_mode', 
            'callback_url', 'cleanup_before_start', 'cleanup_query',
            'use_custom_db', 'db_host', 'db_port', 'db_name', 
            'db_user', 'db_password'
        ]
        widgets = {
            'callback_url': forms.URLInput(attrs={'placeholder': 'https://your-callback-url.com/webhook'}),
            'cleanup_query': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'DELETE FROM table WHERE condition;'
            }),
            'db_password': forms.PasswordInput(render_value=True),
            'db_host': forms.TextInput(attrs={'placeholder': 'localhost'}),
            'db_port': forms.TextInput(attrs={'placeholder': '5432'}),
            'db_name': forms.TextInput(attrs={'placeholder': 'database_name'}),
            'db_user': forms.TextInput(attrs={'placeholder': 'username'}),
        }

class AdditionalTaskForm(forms.ModelForm):
    class Meta:
        model = AdditionalTask
        fields = ['name', 'task_type', 'payload_template', 'order', 'is_enabled']
        widgets = {
            'payload_template': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': '{"key": "value"}'
            }),
        } 
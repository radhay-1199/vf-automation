from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.db import connection, transaction
import json
import time
import requests
import csv
import io
from datetime import datetime
from .models import Flight, FlightEvent, MockConfiguration, AdditionalTask
from .forms import FlightForm, FlightEventForm, MockConfigurationForm, AdditionalTaskForm
from django.db import models
import psycopg2
from django.conf import settings
from django.views.decorators.http import require_http_methods
from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
import socket
import logging
from django.views.decorators.csrf import csrf_protect

# Get logger instance
logger = logging.getLogger(__name__)

class FlightListView(ListView):
    model = Flight
    template_name = 'event_manager/flight_list.html'
    context_object_name = 'flights'

class FlightCreateView(CreateView):
    model = Flight
    form_class = FlightForm
    template_name = 'event_manager/flight_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['config_form'] = MockConfigurationForm(self.request.POST)
        else:
            context['config_form'] = MockConfigurationForm()
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        config_form = context['config_form']
        
        if config_form.is_valid():
            self.object = form.save()
            config = config_form.save(commit=False)
            config.flight = self.object
            config.save()
            messages.success(self.request, 'Flight and configuration created successfully')
            return redirect('flight-detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))
            
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below')
        return super().form_invalid(form)

def flight_detail(request, pk):
    flight = get_object_or_404(Flight, pk=pk)
    events = flight.events.all().order_by('priority', 'created_at')
    config = MockConfiguration.objects.filter(flight=flight).first()
    current_priority = events.filter(is_played=True).order_by('-priority').values_list('priority', flat=True).first() or 0
    
    if request.method == 'POST':
        if 'start_mock' in request.POST:
            return start_mock_session(request, flight)
        elif 'play_event' in request.POST:
            return play_specific_event(request, flight)
        elif 'abort_mock' in request.POST:
            return abort_mock_session(request, flight)
        elif 'reset_mock' in request.POST:
            try:
                flight.events.all().update(is_played=False)
                return JsonResponse({
                    'status': 'success',
                    'message': 'Mock session reset successfully'
                })
            except Exception as e:
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=500)
        elif 'save_config' in request.POST:
            form = MockConfigurationForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                messages.success(request, 'Configuration updated successfully')
            return redirect('flight-detail', pk=flight.pk)
        elif 'run_kafka_task' in request.POST:
            try:
                payload = json.loads(request.POST.get('payload', '{}'))
                # Add your Kafka task execution logic here
                # For example: kafka_producer.send('topic', payload)
                return JsonResponse({'status': 'success', 'message': 'Kafka task executed successfully'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        elif 'run_api_task' in request.POST:
            try:
                payload = json.loads(request.POST.get('payload', '{}'))
                # Add your API task execution logic here
                # For example: requests.post(payload['url'], json=payload['data'])
                return JsonResponse({'status': 'success', 'message': 'API task executed successfully'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        elif 'run_cleanup' in request.POST:
            try:
                # Get the cleanup query or use default if empty
                cleanup_query = request.POST.get('cleanup_query', '').strip()
                if not cleanup_query:
                    cleanup_query = "DELETE FROM flight_status WHERE flight_unique_id = '{flight_unique_id}'"
                
                # Split queries by semicolon and filter out empty ones
                queries = [q.strip() for q in cleanup_query.split(';') if q.strip()]
                success_count = 0
                
                with connection.cursor() as cursor:
                    for query in queries:
                        try:
                            # Format the query with flight_unique_id
                            formatted_query = query.format(flight_unique_id=flight.flight_unique_id)
                            cursor.execute(formatted_query)
                            success_count += 1
                        except Exception as e:
                            return JsonResponse({
                                'status': 'error',
                                'message': f'Query failed: {str(e)}'
                            }, status=400)
                
                return JsonResponse({
                    'status': 'success',
                    'message': f'Successfully executed {success_count} queries'
                })
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    context = {
        'flight': flight,
        'events': events,
        'config': config,
        'config_form': MockConfigurationForm(instance=config),
        'event_form': FlightEventForm(),
        'current_priority': current_priority,
        'api_timeout_ms': getattr(settings, 'API_TIMEOUT_MS', 15000),  # Get timeout from settings with default
    }
    return render(request, 'event_manager/flight_detail.html', context)

def add_event(request, pk):
    flight = get_object_or_404(Flight, pk=pk)
    
    if request.method == 'POST':
        form = FlightEventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.flight = flight
            
            # Handle priority assignment
            requested_priority = event.priority
            max_priority = flight.events.aggregate(models.Max('priority'))['priority__max'] or 0
            
            if requested_priority == 0:  # If no priority specified
                event.priority = max_priority + 1
            elif requested_priority > max_priority:  # If higher priority specified
                event.priority = requested_priority
            else:  # If existing priority specified
                # Shift all events with same or higher priority up by 1
                flight.events.filter(priority__gte=requested_priority).update(
                    priority=models.F('priority') + 1
                )
                event.priority = requested_priority
            
            event.save()
            messages.success(request, 'Event added successfully')
            return redirect('flight-detail', pk=pk)
        else:
            messages.error(request, 'Error adding event')
    
    return redirect('flight-detail', pk=pk)

def play_specific_event(request, flight):
    try:
        event_id = request.POST.get('event_id')
        is_replay = request.POST.get('reset_event') == 'true'
        
        if not event_id:
            raise ValueError("No event_id provided in request")
            
        event = get_object_or_404(FlightEvent, id=event_id, flight=flight)
        
        # Check for configuration first
        config = MockConfiguration.objects.filter(flight=flight).first()
        if not config:
            return JsonResponse({
                'status': 'error',
                'message': 'Mock configuration not found. Please configure callback URL first.',
                'details': {
                    'type': 'configuration_required',
                    'flight_id': flight.id
                }
            }, status=400)
            
        # Get the minimum priority event
        min_priority = flight.events.aggregate(models.Min('priority'))['priority__min']
        
        # Check if we can play this event based on priority
        current_priority = flight.events.filter(is_played=True).order_by('-priority').values_list('priority', flat=True).first() or 0
        
        # Allow replay of first event or if priority is valid
        if not is_replay and event.priority < current_priority and event.priority != min_priority:
            return JsonResponse({
                'status': 'error',
                'message': 'Cannot play this event. Events must be played in sequence.',
                'details': {
                    'event_id': event_id,
                    'is_played': event.is_played,
                    'event_priority': event.priority,
                    'current_priority': current_priority,
                    'min_priority': min_priority,
                    'is_first_event': event.priority == min_priority
                }
            }, status=400)
        
        # Parse raw event and send it
        try:
            event_data = json.loads(event.raw_event)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON for event {event.id}: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Failed to parse event data. Invalid JSON format.',
                'details': {
                    'error': str(e),
                    'raw_event': event.raw_event[:500]  # First 500 chars for debugging
                }
            }, status=400)
            
        # Ensure the payload sent to the callback is always a list
        payload_to_send = None
        if isinstance(event_data, dict):
            # If the parsed data is an object {}, wrap it in a list [{}]
            payload_to_send = [event_data]
            logger.info(f"Wrapping event data object into a list for callback event {event.id}")
        elif isinstance(event_data, list):
            # If it's already a list [...], use it directly
            payload_to_send = event_data
            logger.info(f"Using existing list payload for callback event {event.id}")
        else:
            # Handle unexpected types - log a warning and attempt to send wrapped in a list
            logger.warning(f"Unexpected type for event_data for event {event.id}: {type(event_data)}. Wrapping in list before sending.")
            payload_to_send = [event_data]
            
        if not config.callback_url:
            return JsonResponse({
                'status': 'error',
                'message': 'No callback URL configured. Please set a callback URL in the configuration.',
                'details': {
                    'flight_id': flight.id,
                    'event_id': event_id
                }
            }, status=400)
            
        try:
            # Get timeout from settings or use default
            timeout = getattr(settings, 'API_TIMEOUT_MS', 15000) / 1000  # Convert to seconds
            
            # Log request details before sending
            logger.info(f"---> Sending callback for event {event.id} to URL: {config.callback_url}")
            try:
                # Log payload (use payload_to_send)
                payload_json_str = json.dumps(payload_to_send, indent=2)
                logger.info(f"Callback payload for event {event.id}:\n{payload_json_str}")
            except Exception as json_err:
                logger.error(f"Error formatting payload as JSON for logging: {json_err}")
                logger.info(f"Callback payload (raw) for event {event.id}: {payload_to_send}")

            response = requests.post(
                config.callback_url,
                json=payload_to_send, # Use the modified payload_to_send
                timeout=timeout
            )
            
            # Log response status
            logger.info(f"<--- Callback response status for event {event.id}: {response.status_code}")
            
            # Log response body
            try:
                response_json = response.json()
                response_json_str = json.dumps(response_json, indent=2)
                logger.info(f"Callback response JSON for event {event.id}:\n{response_json_str}")
            except json.JSONDecodeError:
                # Log as text if not JSON
                response_text = response.text
                logger.info(f"Callback response text (first 500 chars) for event {event.id}:\n{response_text[:500]}{'...' if len(response_text) > 500 else ''}")
            except Exception as resp_log_err:
                logger.error(f"Error logging response body: {resp_log_err}")

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        except requests.Timeout as e:
            logger.error(f"Callback request for event {event.id} timed out (URL: {config.callback_url}): {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'Request timed out after {timeout} seconds. The server is not responding.',
                'details': {
                    'timeout': timeout,
                    'url': config.callback_url
                }
            }, status=504)  # Gateway Timeout
        except requests.ConnectionError as e:
            logger.error(f"Callback request for event {event.id} failed to connect (URL: {config.callback_url}): {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Failed to connect to the server. Please check if the callback URL is accessible.',
                'details': {
                    'url': config.callback_url
                }
            }, status=503)  # Service Unavailable
        except requests.RequestException as e:
            # Log the error and the response if available
            error_response_text = e.response.text[:500] + ('...' if len(e.response.text) > 500 else '') if e.response else "No response received"
            logger.error(f"Callback request failed for event {event.id} (URL: {config.callback_url}): {str(e)}\nResponse: {error_response_text}")
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to send event: {str(e)}',
                'details': {
                    'error_type': type(e).__name__,
                    'url': config.callback_url,
                }
            }, status=500)
            
        # If this is a replay, don't update the event state
        if not is_replay:
            event.is_played = True
            event.save()
        
        # Get next event if in fast forward mode
        next_event = None
        if config.fast_forward and not config.manual_mode:
            next_event = flight.events.filter(
                is_played=False,
                priority__gt=event.priority
            ).order_by('priority').first()
        
        if not config.manual_mode and not config.fast_forward:
            time.sleep(config.delay_between_events)
            
        response_data = {
            'status': 'success',
            'message': 'Event played successfully',
            'event_id': event.id,
            'identified_changes': event.identified_changes,
            'flight_state': event.flight_state,
            'priority': event.priority,
            'is_replay': is_replay
        }
        
        # Add next event info if available
        if next_event:
            response_data['next_event'] = {
                'id': next_event.id,
                'priority': next_event.priority
            }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        logger.error(f"Error in play_specific_event: {str(e)}\n{traceback.format_exc()}")
        
        return JsonResponse({
            'status': 'error',
            'message': f'An unexpected error occurred: {str(e)}',
            'details': {
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc()
            }
        }, status=500)

def reset_mock_session(request, flight):
    try:
        # Reset all events to unplayed
        flight.events.all().update(is_played=False)
        
        # Run cleanup queries and capture any errors
        try:
            start_mock_session_internal(request, flight)
            return JsonResponse({
                'status': 'success',
                'message': 'Mock session reset successfully',
                'cleanup_success': True
            })
        except Exception as e:
            # Provide a clearer error message for the UI
            return JsonResponse({
                'status': 'partial_success',  # Changed from 'error' to indicate partial success
                'message': 'Mock session reset but cleanup failed',
                'cleanup_success': False,
                'cleanup_error': str(e)
            }, status=200)  # Return 200 because the reset itself succeeded
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

def abort_mock_session(request, flight):
    try:
        # Run cleanup queries and capture any errors
        try:
            start_mock_session_internal(request, flight)
            messages.info(request, 'Mock session aborted and cleaned up')
            return JsonResponse({
                'status': 'success',
                'message': 'Mock session aborted successfully',
                'cleanup_success': True,
                'aborted_events': []  # Add this to ensure it's defined
            })
        except Exception as e:
            messages.warning(request, f'Mock session aborted but cleanup failed: {str(e)}')
            return JsonResponse({
                'status': 'partial_success',  # Changed from 'error' to indicate partial success
                'message': 'Mock session aborted but cleanup failed',
                'cleanup_success': False,
                'cleanup_error': str(e),
                'aborted_events': []  # Add this to ensure it's defined
            }, status=200)  # Return 200 because the abort itself succeeded
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# Internal version of start_mock_session that doesn't redirect
def start_mock_session_internal(request, flight):
    config = get_object_or_404(MockConfiguration, flight=flight)
    
    # Run custom cleanup query if provided, otherwise run the default query
    if config.cleanup_query:
        # Split queries by semicolon and filter out empty ones
        queries = [q.strip() for q in config.cleanup_query.split(';') if q.strip()]
        
        if config.use_custom_db and all([config.db_host, config.db_name, config.db_user, config.db_password]):
            # Create a new connection to the custom database
            custom_conn = psycopg2.connect(
                host=config.db_host,
                port=config.db_port or "5432",
                database=config.db_name,
                user=config.db_user,
                password=config.db_password
            )
            
            success_count = 0
            with custom_conn.cursor() as cursor:
                for query in queries:
                    try:
                        formatted_query = query.format(flight_unique_id=flight.flight_unique_id)
                        cursor.execute(formatted_query)
                        success_count += 1
                    except Exception as e:
                        error_msg = str(e).split('LINE')[0].strip()
                        raise Exception(f'Query failed: {error_msg}')
            
            custom_conn.commit()
            custom_conn.close()
        else:
            # Use the default database connection
            success_count = 0
            with connection.cursor() as cursor:
                for query in queries:
                    try:
                        formatted_query = query.format(flight_unique_id=flight.flight_unique_id)
                        cursor.execute(formatted_query)
                        success_count += 1
                    except Exception as e:
                        error_msg = str(e).split('LINE')[0].strip()
                        raise Exception(f'Query failed: {error_msg}')
    else:
        # Run the default cleanup query
        default_query = "DELETE FROM flight_status WHERE flight_unique_id = '{flight_unique_id}'"
        with connection.cursor() as cursor:
            cursor.execute(default_query.format(flight_unique_id=flight.flight_unique_id))

    # Reset all events to unplayed
    flight.events.all().update(is_played=False)
    
    # Execute pre-mock tasks
    for task in config.tasks.filter(is_enabled=True).order_by('order'):
        try:
            execute_additional_task(task)
        except Exception as e:
            raise Exception(f'Task {task.name} failed: {str(e)}')
    
    return True

def start_mock_session(request, flight):
    try:
        start_mock_session_internal(request, flight)
        messages.success(request, 'Mock session started')
    except Exception as e:
        # Format the error message consistently with abort/reset functions
        error_message = str(e)
        if "Query failed:" in error_message or "Task" not in error_message:
            messages.error(request, f'Cleanup query failed: {error_message}')
        else:
            messages.error(request, error_message)
    
    return redirect('flight-detail', pk=flight.pk)

def execute_additional_task(task):
    payload = json.loads(task.payload_template)
    if task.task_type == 'kafka':
        # Implement Kafka producer logic here
        # You would typically use kafka-python or confluent-kafka here
        pass
    elif task.task_type == 'api':
        response = requests.post(
            payload.get('url'),
            json=payload.get('body'),
            headers=payload.get('headers', {}),
            timeout=5
        )
        response.raise_for_status()

def get_event_form(request, flight_pk):
    event_id = request.GET.get('event_id')
    event = get_object_or_404(FlightEvent, id=event_id, flight_id=flight_pk)
    form = FlightEventForm(instance=event)
    return render(request, 'event_manager/event_form_fields.html', {'form': form})

def import_events(request, pk):
    if request.method != 'POST':
        return redirect('flight-detail', pk=pk)
    
    flight = get_object_or_404(Flight, pk=pk)
    csv_file = request.FILES.get('csv_file')
    csv_content = request.POST.get('csv_content')
    
    if not csv_file and not csv_content:
        messages.error(request, 'Please provide either a CSV file or paste CSV content')
        return redirect('flight-detail', pk=pk)
    
    try:
        # Process either the uploaded file or pasted content
        if csv_file:
            csv_data = csv_file.read().decode('utf-8')
        else:
            csv_data = csv_content
        
        # Parse CSV data
        csv_io = io.StringIO(csv_data)
        reader = csv.DictReader(csv_io)
        
        # Sort rows by ingestion_time
        rows = sorted(reader, key=lambda x: datetime.strptime(x['ingestion_time'], '%Y-%m-%dT%H:%M:%S'))
        
        with transaction.atomic():
            # Delete existing events for this flight
            flight.events.all().delete()
            
            # Create events with priorities based on sorted order
            for priority, row in enumerate(rows, start=1):
                FlightEvent.objects.create(
                    flight=flight,
                    raw_event=row['raw_event_json'],
                    identified_changes=row['identified_changes'],
                    flight_state=row['flight_state'],
                    priority=priority
                )
        
        messages.success(request, f'Successfully imported {len(rows)} events')
        
    except Exception as e:
        messages.error(request, f'Error importing CSV: {str(e)}')
    
    return redirect('flight-detail', pk=pk)

def delete_flight(request, pk):
    flight = get_object_or_404(Flight, pk=pk)
    if request.method == 'POST':
        flight_id = flight.flight_unique_id
        flight.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': f'Flight {flight_id} has been deleted'})
        messages.success(request, f'Flight {flight_id} has been deleted')
        return redirect('flight-list')
    return redirect('flight-detail', pk=pk)

def delete_event(request, flight_pk, event_pk):
    event = get_object_or_404(FlightEvent, id=event_pk, flight_id=flight_pk)
    if request.method == 'POST':
        event.delete()
        messages.success(request, 'Event has been deleted')
    return redirect('flight-detail', pk=flight_pk)

def edit_event(request, flight_pk, event_pk):
    event = get_object_or_404(FlightEvent, id=event_pk, flight_id=flight_pk)
    if request.method == 'POST':
        form = FlightEventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, 'Event has been updated')
        else:
            messages.error(request, 'Error updating event')
    return redirect('flight-detail', pk=flight_pk)

def get_event(request, flight_pk):
    event_id = request.GET.get('event_id')
    event = get_object_or_404(FlightEvent, id=event_id, flight_id=flight_pk)
    
    # Try to parse raw_event if it's a string
    raw_event = event.raw_event
    try:
        if isinstance(raw_event, str):
            raw_event = json.loads(raw_event)
    except json.JSONDecodeError:
        pass  # Keep original raw_event if parsing fails
    
    return JsonResponse({
        'raw_event': raw_event,
        'identified_changes': event.identified_changes,
        'flight_state': event.flight_state,
        'priority': event.priority
    })

def get_event_with_fid(request, flight_pk):
    flight = get_object_or_404(Flight, pk=flight_pk)
    
    # Get all events sorted by priority
    events = flight.events.all().order_by('priority')
    
    for event in events:
        try:
            raw_event = event.raw_event
            if isinstance(raw_event, str):
                raw_event = json.loads(raw_event)
            
            if isinstance(raw_event, dict) and 'fid' in raw_event:
                return JsonResponse({
                    'raw_event': raw_event,
                    'identified_changes': event.identified_changes,
                    'flight_state': event.flight_state,
                    'priority': event.priority,
                    'event_id': event.id
                })
        except json.JSONDecodeError:
            continue
    
    return JsonResponse({
        'error': 'No event with fid field found',
        'status': 'error'
    }, status=404)

def run_cleanup_query(request, flight_id):
    if request.method == 'POST':
        # Get the flight object
        flight = get_object_or_404(Flight, pk=flight_id)
        config = MockConfiguration.objects.filter(flight=flight).first()
        
        if not config:
            return JsonResponse({
                'status': 'error',
                'message': 'No configuration found for this flight'
            }, status=400)
        
        # Update parameter name to match what's sent from client
        cleanup_query = request.POST.get('cleanup_query', '').strip()
        
        # If no query is provided, use the default query
        if not cleanup_query:
            cleanup_query = "DELETE FROM flight_status WHERE flight_unique_id = '{flight_unique_id}'"
        
        try:
            # Split queries by semicolon and filter out empty ones
            queries = [q.strip() for q in cleanup_query.split(';') if q.strip()]
            success_count = 0
            failed_queries = []
            
            # Check if custom DB should be used
            if config.use_custom_db and all([config.db_host, config.db_name, config.db_user, config.db_password]):
                # Create a new connection to the custom database
                custom_conn = psycopg2.connect(
                    host=config.db_host,
                    port=config.db_port or "5432",
                    database=config.db_name,
                    user=config.db_user,
                    password=config.db_password
                )
                
                try:
                    with custom_conn.cursor() as cursor:
                        for i, query in enumerate(queries):
                            try:
                                # Format the query with flight_unique_id
                                formatted_query = query.format(flight_unique_id=flight.flight_unique_id)
                                cursor.execute(formatted_query)
                                success_count += 1
                            except Exception as e:
                                failed_queries.append({
                                    'query_index': i,
                                    'query': query,
                                    'error': str(e).split("LINE")[0].strip()
                                })
                                # Continue with next query instead of stopping
                    
                    # Commit changes to the custom database
                    custom_conn.commit()
                finally:
                    # Ensure the connection is closed even if an exception occurs
                    custom_conn.close()
            else:
                # Use the default database connection
                with connection.cursor() as cursor:
                    for i, query in enumerate(queries):
                        try:
                            # Format the query with flight_unique_id
                            formatted_query = query.format(flight_unique_id=flight.flight_unique_id)
                            cursor.execute(formatted_query)
                            success_count += 1
                        except Exception as e:
                            failed_queries.append({
                                'query_index': i,
                                'query': query,
                                'error': str(e).split("LINE")[0].strip()
                            })
                            # Continue with next query instead of stopping
            
            # Construct response message
            if success_count == len(queries):
                return JsonResponse({
                    'status': 'success',
                    'message': f'Successfully executed all {success_count} queries'
                })
            elif success_count > 0:
                return JsonResponse({
                    'status': 'partial_success',
                    'message': f'Executed {success_count} of {len(queries)} queries successfully',
                    'failed_queries': failed_queries
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'All queries failed',
                    'failed_queries': failed_queries
                }, status=500)
                
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({
            'status': 'error',
            'message': 'Only POST method is allowed'
        }, status=405)

def delete_all_events(request, flight_pk):
    flight = get_object_or_404(Flight, pk=flight_pk)
    if request.method == 'POST':
        flight.events.all().delete()
        messages.success(request, 'All events have been deleted')
    return redirect('flight-detail', pk=flight_pk)

@require_http_methods(["POST"])
def produce_kafka_event(request):
    try:
        logger.info("Starting Kafka event production")
        
        data = json.loads(request.body)
        logger.info(f"Received data: {data}")
        
        bootstrap_servers = data.get('bootstrapServers')
        topic_name = data.get('topicName')
        payload = data.get('payload')

        logger.info(f"Bootstrap servers: {bootstrap_servers}")
        logger.info(f"Topic name: {topic_name}")
        logger.info(f"Payload type: {type(payload)}")
        logger.info(f"Raw payload: {payload}")

        if not all([bootstrap_servers, topic_name, payload]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        # Basic Kafka producer configuration
        conf = {
            'bootstrap.servers': bootstrap_servers,
            'client.id': socket.gethostname()
        }

        try:
            # Parse payload if it's a string
            message_payload = json.loads(payload) if isinstance(payload, str) else payload
            logger.info(f"Parsed message payload type: {type(message_payload)}")
            
            # Convert dict to JSON string and then to bytes
            message_bytes = json.dumps(message_payload).encode('utf-8')
            logger.info(f"Message bytes type: {type(message_bytes)}")
            
            # Create producer instance
            producer = Producer(conf)
            
            # Delivery callback
            def delivery_callback(err, msg):
                if err:
                    logger.error(f"Message delivery failed: {str(err)}")
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Message delivery failed: {str(err)}'
                    }, status=500)
                else:
                    logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")

            # Produce message
            producer.produce(
                topic=topic_name,
                value=message_bytes,  # Use the bytes version of the message
                callback=delivery_callback
            )
            
            # Wait for message delivery
            producer.flush(timeout=10)
            
            return JsonResponse({
                'status': 'success',
                'message': 'Event produced successfully',
                'details': {
                    'topic': topic_name,
                    'timestamp': producer.flush()
                }
            })
            
        except Exception as e:
            logger.error(f"Error producing message: {str(e)}", exc_info=True)
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to produce event: {str(e)}'
            }, status=500)
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON payload: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON payload'
        }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@csrf_protect
@require_http_methods(["POST"])
def transform_payload(request):
    try:
        data = json.loads(request.body)
        raw_event = data.get('raw_event')
        host_address = data.get('host_address')
        
        if not raw_event or not host_address:
            return JsonResponse(
                {'message': 'Missing required parameters: raw_event or host_address'}, 
                status=400
            )
            
        # Make the request to the external API
        transform_url = f"{host_address}/nav/v1/internal/create-flight-detail-dto-v2"
        response = requests.post(
            transform_url,
            json=raw_event,
            headers={'Content-Type': 'application/json'},
            timeout=10  # 10 seconds timeout
        )
        
        # Check if the response was successful
        response.raise_for_status()
        
        # Try to parse the response as JSON
        try:
            transformed_data = response.json()
            return JsonResponse(transformed_data)
        except ValueError:
            return JsonResponse(
                {'message': 'Invalid JSON response from transformation service'}, 
                status=502
            )
            
    except requests.RequestException as e:
        error_msg = str(e)
        if 'ConnectionError' in error_msg:
            error_msg = 'Could not connect to transformation service'
        elif 'Timeout' in error_msg:
            error_msg = 'Transformation service request timed out'
        return JsonResponse(
            {'message': f'Failed to reach transformation service: {error_msg}'}, 
            status=502
        )
    except ValueError as e:
        return JsonResponse(
            {'message': f'Invalid JSON in request: {str(e)}'}, 
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'message': f'Internal server error: {str(e)}'}, 
            status=500
        )

@csrf_protect
@require_http_methods(["POST"])
def proxy_api_request(request):
    try:
        print(">>> PROXY API REQUEST CALLED <<<")
        data = json.loads(request.body)
        payload = data.get('payload')
        target_url = data.get('url')
        headers = data.get('headers', {})
        
        print(f"Proxying request to: {target_url}")
        print(f"Headers: {headers}")
        print(f"Payload: {payload}")
        
        # Ensure all header values are strings
        string_headers = {str(k): str(v) for k, v in headers.items() if v is not None}
        
        if not payload or not target_url:
            print("Missing required parameters")
            return JsonResponse(
                {'message': 'Missing required parameters: payload or url'}, 
                status=400
            )
        
        # Make the request to the external API
        response = requests.post(
            target_url,
            json=payload if isinstance(payload, dict) else json.loads(payload),
            headers=string_headers, # Use stringified headers
            timeout=15  # 15 seconds timeout
        )
        
        print(f"Response status code: {response.status_code}")
        
        # Get the response content
        try:
            response_content = response.json()
            print(f"Response content: {response_content}")
        except ValueError:
            response_content = {'text': response.text}
            print(f"Text response content: {response.text[:200]}...")
        
        # Return the response with status code and headers
        return JsonResponse({
            'status': response.status_code,
            'content': response_content,
            'headers': dict(response.headers)
        })
        
    except requests.RequestException as e:
        error_msg = str(e)
        print(f"Request exception: {error_msg}")
        if 'ConnectionError' in error_msg:
            error_msg = 'Could not connect to target service'
        elif 'Timeout' in error_msg:
            error_msg = 'Request timed out'
        return JsonResponse(
            {'message': f'Failed to reach target service: {error_msg}'}, 
            status=502
        )
    except ValueError as e:
        print(f"Value error: {str(e)}")
        return JsonResponse(
            {'message': f'Invalid JSON in request: {str(e)}'}, 
            status=400
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return JsonResponse(
            {'message': f'Internal server error: {str(e)}'}, 
            status=500
        )

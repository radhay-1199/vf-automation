from django.http import JsonResponse
from django.utils import timezone
from .models import Flight, FlightEvent
import json
from datetime import datetime

def flight_query(request):
    """
    API endpoint to query flight information.
    Query params:
    - fnum: Flight number
    - date: Date in format yyyyMMdd
    Returns flight information if found, null if not found.
    """
    fnum = request.GET.get('fnum')
    date_str = request.GET.get('date')

    if not fnum or not date_str:
        return JsonResponse({'error': 'Missing required parameters'}, status=400)

    try:
        # Parse the date from yyyyMMdd to ddMMyyyy for flight unique id
        date_obj = datetime.strptime(date_str, '%Y%m%d')
        date_formatted = date_obj.strftime('%d%m%Y')

        # Find events with FIRST_NAV_TRACKING in identified_changes
        events = FlightEvent.objects.filter(
            flight__flight_unique_id__contains=fnum,
            identified_changes__icontains='FIRST_NAV_TRACKING'
        ).select_related('flight')

        for event in events:
            # Extract flight unique id components
            flight_id = event.flight.flight_unique_id
            if date_formatted in flight_id:
                try:
                    event_data = json.loads(event.raw_event)
                    return JsonResponse(event_data)
                except json.JSONDecodeError:
                    continue

        return JsonResponse(None, safe=False)

    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

def add_flight_push(request):
    """
    API endpoint for flight push.
    Always returns error code 8 only.
    """
    return JsonResponse({
        'errorCode': 8
    }) 
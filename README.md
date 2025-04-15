# Flight Event Mock Service

A Django-based service for mocking and replaying flight events for testing purposes. This service allows you to simulate flight tracking events by sending them to your callback endpoints in a controlled manner.

## Features

- Create and manage multiple flight tracks
- Add and organize flight events with priorities
- Configure mock settings (delay, fast-forward, manual mode)
- Support for additional tasks (Kafka events, API calls)
- Clean and intuitive UI
- Event playback controls (start, next, abort)
- Visual feedback for played events

## Setup

1. Create a virtual environment and activate it:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up PostgreSQL database and update settings in `flight_mock/settings.py`

4. Run migrations:
```bash
python manage.py makemigrations
python manage.py migrate
```

5. Create a superuser:
```bash
python manage.py createsuperuser
```

6. Run the development server:
```bash
python manage.py runserver
```

## Usage

1. Access the application at `http://localhost:8000`
2. Add a new flight using the "Add New Flight" button
3. Configure mock settings for the flight
4. Add events to the flight with their respective priorities and states
5. Use the mock controls to start, play next event, or abort the mock session

## Additional Tasks

You can configure additional tasks to run before starting the mock session:

1. Kafka Events: Configure Kafka producer settings and payload
2. API Calls: Set up API endpoints and request bodies
3. Cleanup Tasks: Define cleanup operations before mock sessions

## Contributing

Feel free to submit issues and enhancement requests! 
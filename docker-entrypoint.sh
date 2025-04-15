#!/bin/bash

# Function to wait for postgres
wait_for_postgres() {
    until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q'; do
        echo "PostgreSQL is unavailable - sleeping"
        sleep 1
    done
    echo "PostgreSQL is up"
}

# Function to collect static files
collect_static() {
    echo "Collecting static files"
    python manage.py collectstatic --noinput
}

# Function to run migrations
run_migrations() {
    echo "Running migrations"
    python manage.py migrate --noinput
}

# Main execution
if [ "$DJANGO_ENV" = "development" ]; then
    wait_for_postgres
    collect_static
    run_migrations
    echo "Starting development server"
    uvicorn flight_mock.asgi:application --host 0.0.0.0 --port 8000 --reload
else
    wait_for_postgres
    collect_static
    run_migrations
    echo "Starting production server with ${GUNICORN_WORKERS:-4} workers"
    gunicorn flight_mock.asgi:application \
        -w ${GUNICORN_WORKERS:-4} \
        --threads ${GUNICORN_THREADS:-2} \
        -k uvicorn.workers.UvicornWorker \
        -b 0.0.0.0:8000 
fi 
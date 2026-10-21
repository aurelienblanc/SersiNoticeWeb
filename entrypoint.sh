#!/bin/sh
set -eu
python manage.py migrate --noinput
exec gunicorn sersi_web.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 180 --access-logfile - --error-logfile -

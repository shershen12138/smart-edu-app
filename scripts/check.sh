#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test school.tests

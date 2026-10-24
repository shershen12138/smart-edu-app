FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY . /app
RUN useradd --create-home --uid 10001 coursejudge && mkdir -p /app/.runtime /storage && chown -R coursejudge:coursejudge /app /storage
USER coursejudge
RUN DEBUG=true SECRET_KEY=build-only-static-collection python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--threads=8", "config.wsgi:application"]

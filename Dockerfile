FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SERSI_DEBUG=0 SERSI_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN SERSI_SECRET_KEY=temporary-build-key-not-used-at-runtime python manage.py collectstatic --noinput \
    && groupadd --gid 10001 sersi \
    && useradd --uid 10001 --gid sersi --no-create-home sersi \
    && mkdir -p /data/documents \
    && chown -R sersi:sersi /app /data
USER sersi
EXPOSE 8000
CMD ["sh", "entrypoint.sh"]

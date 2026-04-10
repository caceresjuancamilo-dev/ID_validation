FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Forzar reinstalación de browsers con dependencias del sistema
RUN python -m playwright install --with-deps chromium

COPY *.py .

CMD gunicorn --bind 0.0.0.0:$PORT --timeout 180 --workers 1 --log-level debug --preload runt_api:app

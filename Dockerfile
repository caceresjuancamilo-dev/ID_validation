FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium   # ← AGREGAR ESTA LÍNEA

COPY *.py .

EXPOSE 5050

# ← CAMBIAR los corchetes por forma shell para que $PORT se expanda
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 180 --workers 1 runt_api:app

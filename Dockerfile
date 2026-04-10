FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium --with-deps

COPY *.py .

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:$PORT --timeout 180 --workers 1 --log-level debug runt_api:app

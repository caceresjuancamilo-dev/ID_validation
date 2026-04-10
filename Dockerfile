FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Forzar reinstalación de browsers con dependencias del sistema
RUN python -m playwright install --with-deps chromium

COPY *.py .

CMD python -c "import runt_api; print('OK')"

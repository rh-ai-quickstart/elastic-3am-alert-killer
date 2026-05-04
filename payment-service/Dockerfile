FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as non-root (required by OpenShift)
RUN useradd -r -u 1001 appuser
USER 1001

EXPOSE 8080

CMD ["opentelemetry-instrument", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
CMD ["sh", "-c", "gunicorn --workers 2 --threads 4 --timeout 30 --bind 0.0.0.0:\u0024{PORT:-8000} wsgi:app"]

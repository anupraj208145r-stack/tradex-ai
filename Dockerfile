FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /app/data
COPY backend ./backend
COPY frontend ./frontend
EXPOSE 8000
# Railway injects PORT at runtime; keep 8000 as the local Docker default.
CMD ["sh","-c","exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

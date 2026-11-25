FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY sample_data ./sample_data

ENV PYTHONPATH=/app/backend
ENV PULSIFI_DB_PATH=/app/data/pulsifi_credit_mvp.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

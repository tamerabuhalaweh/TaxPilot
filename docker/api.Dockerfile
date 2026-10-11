FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/apps/api
COPY apps/api/requirements.txt apps/api/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api/app ./app
COPY apps/api/worker ./worker
COPY db /srv/db
ENV PYTHONPATH=/srv/apps/api:/srv
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

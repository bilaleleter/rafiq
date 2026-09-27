# Optional: everything in one container (backend serves the built frontend on the same URL).
# docker build -t rafiq . && docker run -p 8000:8000 --env-file backend/.env rafiq
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/dist ./static
ENV DEV_MODE=0 DEMO_MODE=1 PORT=8000
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT --timeout-graceful-shutdown 3

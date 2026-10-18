FROM node:22-alpine AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY vite.config.js ./
COPY resources ./resources
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY resources/views/queue.html ./resources/views/queue.html
COPY --from=frontend /app/public/build ./public/build
COPY --from=frontend /app/resources/views/assets.json ./resources/views/assets.json
COPY --from=frontend /app/resources/views/build ./resources/views/build
RUN useradd --create-home queue && mkdir -p /data && chown queue:queue /data
USER queue
ENV DATABASE_URL=sqlite:////data/database.sqlite
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]

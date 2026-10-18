FROM node:22-alpine AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY vite.config.js ./
COPY resources ./resources
RUN npm run build

FROM php:8.4-cli-alpine
RUN apk add --no-cache icu-dev libzip-dev sqlite-dev postgresql-dev oniguruma-dev \
    && docker-php-ext-install intl zip pdo_sqlite pdo_pgsql pdo_mysql mbstring bcmath pcntl
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
WORKDIR /app
COPY . .
RUN composer install --no-dev --prefer-dist --optimize-autoloader --no-interaction \
    && mkdir -p /data storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
    && chown -R www-data:www-data /app /data
COPY --from=frontend /app/public/build ./public/build
USER www-data
ENV APP_ENV=production APP_DEBUG=false LOG_CHANNEL=stderr SESSION_DRIVER=file CACHE_STORE=file QUEUE_CONNECTION=sync DB_CONNECTION=sqlite DB_DATABASE=/data/database.sqlite
EXPOSE 8080
CMD ["sh", "docker/start.sh"]
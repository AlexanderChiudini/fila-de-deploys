#!/bin/sh
set -eu
if [ -z "${APP_KEY:-}" ]; then
    echo "Configure APP_KEY antes de iniciar o aplicativo." >&2
    exit 1
fi
if [ "${DB_CONNECTION:-sqlite}" = "sqlite" ]; then
    mkdir -p "$(dirname "$DB_DATABASE")"
    touch "$DB_DATABASE"
fi
php artisan migrate --force
php artisan config:cache
php artisan view:cache
exec php artisan serve --host=0.0.0.0 --port="${PORT:-8080}" --no-reload
#!/bin/bash
set -e

echo "=========================================================="
echo " Starting Laravel Container Setup"
echo "=========================================================="

echo "[1/4] Waiting for PostgreSQL database (${DB_HOST}:${DB_PORT}) to become ready..."
until php -r "try { new PDO('pgsql:host=' . getenv('DB_HOST') . ';port=' . getenv('DB_PORT') . ';dbname=' . getenv('DB_DATABASE'), getenv('DB_USERNAME'), getenv('DB_PASSWORD')); exit(0); } catch (Exception \$e) { exit(1); }"; do
    echo "  -> Database not ready yet... retrying in 2 seconds"
    sleep 2
done
echo "  -> PostgreSQL database connection established successfully."

echo "[2/4] Initializing environment and permissions..."
if [ ! -f .env ]; then
    echo "  -> Creating .env from .env.example..."
    cp .env.example .env
fi

if ! grep -q "APP_KEY=base64:" .env && [ -z "$APP_KEY" ]; then
    echo "  -> Generating Laravel application key..."
    php artisan key:generate --force
fi

mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs bootstrap/cache
chmod -R 777 storage bootstrap/cache

echo "[3/4] Running database schema migrations..."
php artisan migrate --force

echo "[4/4] Starting Laravel server on http://0.0.0.0:8000..."
echo "=========================================================="
exec php artisan serve --host=0.0.0.0 --port=8000

#!/bin/sh
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

# Ensure container environment variables are reflected inside .env
[ -n "$DB_CONNECTION" ] && (grep -q "^DB_CONNECTION=" .env && sed -i "s/^DB_CONNECTION=.*/DB_CONNECTION=${DB_CONNECTION}/" .env || echo "DB_CONNECTION=${DB_CONNECTION}" >> .env)
[ -n "$DB_HOST" ] && (grep -q "^DB_HOST=" .env && sed -i "s/^DB_HOST=.*/DB_HOST=${DB_HOST}/" .env || echo "DB_HOST=${DB_HOST}" >> .env)
[ -n "$DB_PORT" ] && (grep -q "^DB_PORT=" .env && sed -i "s/^DB_PORT=.*/DB_PORT=${DB_PORT}/" .env || echo "DB_PORT=${DB_PORT}" >> .env)
[ -n "$DB_DATABASE" ] && (grep -q "^DB_DATABASE=" .env && sed -i "s/^DB_DATABASE=.*/DB_DATABASE=${DB_DATABASE}/" .env || echo "DB_DATABASE=${DB_DATABASE}" >> .env)
[ -n "$DB_USERNAME" ] && (grep -q "^DB_USERNAME=" .env && sed -i "s/^DB_USERNAME=.*/DB_USERNAME=${DB_USERNAME}/" .env || echo "DB_USERNAME=${DB_USERNAME}" >> .env)
[ -n "$DB_PASSWORD" ] && (grep -q "^DB_PASSWORD=" .env && sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=${DB_PASSWORD}/" .env || echo "DB_PASSWORD=${DB_PASSWORD}" >> .env)
[ -n "$PYTHON_PIPELINE_URL" ] && (grep -q "^PYTHON_PIPELINE_URL=" .env && sed -i "s|^PYTHON_PIPELINE_URL=.*|PYTHON_PIPELINE_URL=${PYTHON_PIPELINE_URL}|" .env || echo "PYTHON_PIPELINE_URL=${PYTHON_PIPELINE_URL}" >> .env)
[ -n "$FORECAST_SERVICE_URL" ] && (grep -q "^FORECAST_SERVICE_URL=" .env && sed -i "s|^FORECAST_SERVICE_URL=.*|FORECAST_SERVICE_URL=${FORECAST_SERVICE_URL}|" .env || echo "FORECAST_SERVICE_URL=${FORECAST_SERVICE_URL}" >> .env)
[ -n "$SCRAPER_SERVICE_URL" ] && (grep -q "^SCRAPER_SERVICE_URL=" .env && sed -i "s|^SCRAPER_SERVICE_URL=.*|SCRAPER_SERVICE_URL=${SCRAPER_SERVICE_URL}|" .env || echo "SCRAPER_SERVICE_URL=${SCRAPER_SERVICE_URL}" >> .env)

if ! grep -q "APP_KEY=base64:" .env && [ -z "$APP_KEY" ]; then
    echo "  -> Generating Laravel application key..."
    php artisan key:generate --force
fi

mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs bootstrap/cache
chmod -R 777 storage bootstrap/cache

# Clear any cached configuration
php artisan config:clear || true

echo "[3/4] Running database schema migrations..."
php artisan migrate --force

echo "[4/4] Starting Laravel server on http://0.0.0.0:8000..."
echo "=========================================================="
exec php artisan serve --host=0.0.0.0 --port=8000

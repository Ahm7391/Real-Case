# Agent Guidelines & Repository Rules

## 1. Project Directory Focus
- **Active Python Pipeline**: Always work inside `copy-kerja-real/Real-Case/Forecast Service/`.
- **Active Laravel Backend**: Always work inside `laravel-be/Laravel-BE/`.
- **Deprecated / Do Not Use**: Do **NOT** use or modify files inside `Ecommerce-Project/` (or `Ecommerce Project`).

## 2. Database & Migration Rules (STRICT)
- **NO DESTRUCTIVE ARTISAN COMMANDS**: Never run commands that can alter, wipe, or tamper with the database (e.g., `php artisan migrate:fresh`, `php artisan migrate:reset`, `php artisan migrate:rollback`, `php artisan db:seed`).
- **NO AUTOMATIC MIGRATION RUNS**: The **user will always run `php artisan migrate` manually**. Agents must NOT run `php artisan migrate`.

## 3. Testing & Verification Rules (STRICT)
- **NO AUTOMATED TEST SUITES**: Do not run automatic PHPUnit/Pest test suites (especially those utilizing `RefreshDatabase` or database wiping traits).
- **ONLY LINTING / SYNTAX CHECKS ALLOWED**: Only use `php -l <filepath>` or static analysis/linters to verify PHP code changes.

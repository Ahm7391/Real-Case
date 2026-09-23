# Agent Guidelines & Safety Rules

## ⚠️ Critical Safety: Non-Destructive Database Policy
- **NEVER run destructive database commands** under any circumstances, including but not limited to:
  - `php artisan migrate:fresh`
  - `php artisan migrate:refresh`
  - `php artisan migrate:reset`
  - `php artisan db:wipe`
  - Any custom or raw commands that drop tables, truncate tables, or wipe DB data.
- **NEVER use the `RefreshDatabase` trait / library** or any testing mechanism that wipes or rolls back existing database records.
- Preserve all existing database data at all times.

## 🧪 Testing & Verification Policy
- **Do not run destructive or live integration tests automatically.**
- **Agent Lint Checks Only:** The agent may only perform static lint checks (e.g. `php -l <file>`).
- **User-Led Testing:** All functional, manual, or integration testing must be left to the user.
- **Provide Test Steps:** Whenever code or scripts need to be tested, clearly provide the user with:
  1. Key test points (what needs to be validated).
  2. Step-by-step instructions for the user to perform the verification.


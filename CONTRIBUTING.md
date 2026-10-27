# Розробка

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

## Локальний Home Assistant

Локальний Home Assistant у Docker (`docker-compose.yml`). Конфіг лежить у
`.ha-config/` (в `.gitignore`), а `custom_components/svitlo_ye` підключено
bind mount-ом, тому правки в коді видно без копіювання.

```bash
docker compose up -d              # запуск, http://localhost:8123
docker compose logs -f            # логи (debug для custom_components.svitlo_ye)
docker compose restart            # перезапуск після змін у manifest/const
docker compose down               # зупинка
```

1. Перший раз відкрийте http://localhost:8123 і створіть користувача.
2. **Налаштування → Пристрої та служби → Додати інтеграцію → СвітлоЄ?**.
3. Після змін у коді: **Пристрої та служби → СвітлоЄ? → ⋮ → Перезавантажити**.
   Для змін у `manifest.json`, `const.py` або нових платформ — `docker compose restart`.

Справжні відповіді API для тестів лежать у `tests/fixtures/` (знято 27.10.2026).


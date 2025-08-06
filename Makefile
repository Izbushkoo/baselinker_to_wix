# BaseLinker to Wix - Makefile
# Команды для управления проектом

# Экспорт переменных окружения для правильных разрешений файлов
export UID := $(shell id -u)
export GID := $(shell id -g)

.PHONY: help build up down logs shell migration upgrade db-current db-history clean

# Показать справку
help:
	@echo "Доступные команды:"
	@echo "  build         - Пересобрать Docker образы"
	@echo "  up            - Запустить все сервисы"
	@echo "  down          - Остановить все сервисы"
	@echo "  logs          - Показать логи всех сервисов"
	@echo "  logs-app      - Показать логи приложения"
	@echo "  logs-worker   - Показать логи Celery worker"
	@echo "  logs-beat     - Показать логи Celery beat"
	@echo "  logs-redis    - Показать логи Redis"
	@echo "  logs-postgres - Показать логи PostgreSQL"
	@echo "  logs-flower   - Показать логи Flower"
	@echo "  shell         - Подключиться к контейнеру приложения"
	@echo "  migration     - Создать новую миграцию"
	@echo "  upgrade       - Применить миграции к БД"
	@echo "  db-current    - Показать текущую ревизию БД"
	@echo "  db-history    - Показать историю миграций"
	@echo "  clean         - Очистить Docker образы и volumes"
	@echo "  fix-permissions - Исправить права доступа к файлам"

# Docker команды
build:
	docker compose build

up: fix-permissions
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs --follow --tail=100

shell:
	docker compose exec app bash

# Команды для просмотра логов отдельных сервисов
logs-app:
	docker compose logs --follow --tail=50 app

logs-worker:
	docker compose logs --follow --tail=50 celery_worker

logs-beat:
	docker compose logs --follow --tail=50 celery_beat

logs-redis:
	docker compose logs --follow --tail=50 redis

logs-postgres:
	docker compose logs --follow --tail=50 postgres

logs-flower:
	docker compose logs --follow --tail=50 flower

# Команды для работы с базой данных и миграциями
migration:
	@echo "Создание новой миграции..."
	@read -p "Введите описание миграции: " message; \
	docker compose exec app poetry run alembic revision --autogenerate -m "$$message"

upgrade:
	@echo "Применение миграций к базе данных..."
	docker compose exec app poetry run alembic upgrade head

db-current:
	@echo "Текущая ревизия базы данных:"
	docker compose exec app poetry run alembic current

db-history:
	@echo "История миграций:"
	docker compose exec app poetry run alembic history

# Полная очистка
clean:
	docker compose down -v
	docker system prune -f

# Перезапуск с пересборкой
restart: down build up

# Быстрый запуск для разработки
dev: up logs

# Создание env файла из примера
env:
	@if [ ! -f .env.docker ]; then \
		cp example.env .env.docker; \
		echo ".env.docker файл создан из example.env"; \
	else \
		echo ".env.docker файл уже существует"; \
	fi

# Исправление прав доступа к файлам
fix-permissions:
	@echo "Создание необходимых папок и исправление прав доступа..."
	@mkdir -p ./app/logs
	@mkdir -p ./migrations/versions
	@sudo chown -R $(UID):$(GID) ./app/logs
	@sudo chown -R $(UID):$(GID) ./migrations 2>/dev/null || true
	@sudo chown $(UID):$(GID) ./celerybeat-schedule 2>/dev/null || true
	@chmod 755 ./app/logs
	@chmod 755 ./migrations
	@chmod 755 ./migrations/versions 2>/dev/null || true
	@chmod 644 ./celerybeat-schedule 2>/dev/null || true
	@touch ./app/logs/.gitkeep
	@echo "Права доступа исправлены"
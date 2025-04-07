FROM python:3.10-bookworm
LABEL authors="Izbushko"

# Установка системных утилит (включая pg_dump)
# Устанавливаем pg_dump (PostgreSQL 15) из штатного репозитория Bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*# Установка Poetry

RUN pip install poetry==1.6.1

# Настройка переменных окружения Poetry
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache \
    POETRY_PYTHON=/usr/local/bin/python3.10

# Создание рабочей директории
WORKDIR /app

# Копирование файлов зависимостей
COPY pyproject.toml poetry.lock ./
RUN touch README.md

# Установка зависимостей
RUN poetry env use /usr/local/bin/python3.10 && poetry install --no-root && rm -rf $POETRY_CACHE_DIR

# Копирование исходного кода
COPY . .

# Установка проекта
RUN poetry env use /usr/local/bin/python3.10 && poetry install

# Делаем скрипт запуска исполняемым
RUN chmod +x docker-entrypoint.sh

# Открываем порт
EXPOSE 8787

# Запускаем приложение
CMD ["./docker-entrypoint.sh"]

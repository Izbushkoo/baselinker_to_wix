#!/bin/bash

# Активируем виртуальное окружение Poetry
VENV_PATH=$(poetry env info --path)
source "$VENV_PATH/bin/activate"

# Добавляем путь к исполняемым файлам виртуального окружения
export PATH="$VENV_PATH/bin:$PATH"

# Запускаем основной сервис
exec uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload 
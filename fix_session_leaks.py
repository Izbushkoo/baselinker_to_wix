#!/usr/bin/env python3
"""
Скрипт для поиска и анализа потенциальных утечек сессий базы данных.
Ищет использование SessionLocal() без контекстных менеджеров.
"""

import os
import re
import sys
from pathlib import Path

def find_session_issues(directory):
    """Поиск потенциальных проблем с сессиями в Python файлах."""
    issues = []
    
    for root, dirs, files in os.walk(directory):
        # Пропускаем виртуальные окружения и кеш
        if any(skip in root for skip in ['venv', '__pycache__', '.git', 'node_modules']):
            continue
            
        for file in files:
            if not file.endswith('.py'):
                continue
                
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                    
                    # Поиск проблемных паттернов
                    for i, line in enumerate(lines, 1):
                        line_stripped = line.strip()
                        
                        # 1. SessionLocal() без with statement
                        if re.search(r'session\s*=\s*SessionLocal\(\)', line_stripped):
                            # Проверяем, есть ли with в соседних строках
                            context_start = max(0, i-3)
                            context_end = min(len(lines), i+3)
                            context = '\n'.join(lines[context_start:context_end])
                            
                            if 'with ' not in context:
                                issues.append({
                                    'file': filepath,
                                    'line': i,
                                    'issue': 'SessionLocal без with statement',
                                    'code': line_stripped,
                                    'severity': 'HIGH'
                                })
                        
                        # 2. session.close() в finally блоках (может быть излишним)
                        if 'session.close()' in line_stripped and 'finally:' in '\n'.join(lines[max(0,i-5):i]):
                            issues.append({
                                'file': filepath,
                                'line': i,
                                'issue': 'Ручное закрытие сессии в finally (может быть излишним)',
                                'code': line_stripped,
                                'severity': 'MEDIUM'
                            })
                            
                        # 3. Long-running tasks без правильного управления сессиями
                        if '@celery.task' in line_stripped:
                            # Проверяем следующие 50 строк на наличие SessionLocal
                            task_context = '\n'.join(lines[i:min(len(lines), i+50)])
                            if 'SessionLocal()' in task_context and 'with ' not in task_context:
                                issues.append({
                                    'file': filepath,
                                    'line': i,
                                    'issue': 'Celery task без правильного управления сессиями',
                                    'code': line_stripped,
                                    'severity': 'HIGH'
                                })
                        
                        # 4. Потенциальные длительные операции
                        if any(pattern in line_stripped.lower() for pattern in ['time.sleep', 'requests.', 'http']):
                            # Ищем SessionLocal в контексте ±10 строк
                            context_start = max(0, i-10)
                            context_end = min(len(lines), i+10)
                            context = '\n'.join(lines[context_start:context_end])
                            
                            if 'SessionLocal()' in context:
                                issues.append({
                                    'file': filepath,
                                    'line': i,
                                    'issue': 'Потенциально длительная операция рядом с SessionLocal',
                                    'code': line_stripped,
                                    'severity': 'MEDIUM'
                                })
                                
            except Exception as e:
                print(f"Ошибка при чтении {filepath}: {e}")
                continue
    
    return issues

def analyze_database_config(directory):
    """Анализ конфигурации базы данных."""
    db_config_files = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file in ['database.py', 'config.py', 'settings.py']:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'create_engine' in content or 'pool_size' in content:
                            db_config_files.append({
                                'file': filepath,
                                'content': content
                            })
                except:
                    continue
    
    return db_config_files

def generate_report(issues, db_configs):
    """Генерация отчёта о найденных проблемах."""
    print("=" * 80)
    print("АНАЛИЗ УТЕЧЕК СЕССИЙ БАЗЫ ДАННЫХ")
    print("=" * 80)
    
    # Группировка по серьёзности
    high_issues = [i for i in issues if i['severity'] == 'HIGH']
    medium_issues = [i for i in issues if i['severity'] == 'MEDIUM']
    
    print(f"\nНайдено проблем: {len(issues)}")
    print(f"  - Высокой важности: {len(high_issues)}")
    print(f"  - Средней важности: {len(medium_issues)}")
    
    # Высокой важности
    if high_issues:
        print("\n" + "="*50)
        print("КРИТИЧЕСКИЕ ПРОБЛЕМЫ (требуют немедленного исправления)")
        print("="*50)
        
        for issue in high_issues:
            print(f"\nФайл: {issue['file']}")
            print(f"Строка: {issue['line']}")
            print(f"Проблема: {issue['issue']}")
            print(f"Код: {issue['code']}")
    
    # Средней важности
    if medium_issues:
        print("\n" + "="*50)
        print("ПРОБЛЕМЫ СРЕДНЕЙ ВАЖНОСТИ")
        print("="*50)
        
        for issue in medium_issues:
            print(f"\nФайл: {issue['file']}")
            print(f"Строка: {issue['line']}")
            print(f"Проблема: {issue['issue']}")
            print(f"Код: {issue['code']}")
    
    # Конфигурация БД
    if db_configs:
        print("\n" + "="*50)
        print("КОНФИГУРАЦИЯ БАЗЫ ДАННЫХ")
        print("="*50)
        
        for config in db_configs:
            print(f"\nФайл: {config['file']}")
            
            # Извлекаем настройки пула
            content = config['content']
            pool_size = re.search(r'pool_size\s*=\s*(\d+)', content)
            max_overflow = re.search(r'max_overflow\s*=\s*(\d+)', content)
            pool_timeout = re.search(r'pool_timeout\s*=\s*(\d+)', content)
            
            if pool_size:
                print(f"  pool_size: {pool_size.group(1)}")
            if max_overflow:
                print(f"  max_overflow: {max_overflow.group(1)}")
            if pool_timeout:
                print(f"  pool_timeout: {pool_timeout.group(1)}")
                
            if not (pool_size and max_overflow):
                print("  ⚠️  Настройки пула не найдены или используются значения по умолчанию")

def generate_recommendations():
    """Генерация рекомендаций по исправлению."""
    print("\n" + "="*80)
    print("РЕКОМЕНДАЦИИ ПО ИСПРАВЛЕНИЮ")
    print("="*80)
    
    recommendations = [
        "1. Замените все SessionLocal() на get_celery_session() в Celery задачах",
        "2. Используйте контекстные менеджеры: with get_celery_session() as session:",
        "3. Удалите ручные session.close() при использовании with statement",
        "4. Увеличьте размер пула соединений до 20-50 в database.py",
        "5. Добавьте отдельный пул для Celery задач",
        "6. Установите pool_timeout=60 и pool_recycle=3600",
        "7. Добавьте мониторинг активных соединений",
        "8. Рассмотрите использование connection pooler (pgbouncer)",
    ]
    
    for rec in recommendations:
        print(rec)

def main():
    if len(sys.argv) != 2:
        print("Использование: python fix_session_leaks.py <путь_к_проекту>")
        sys.exit(1)
    
    project_path = sys.argv[1]
    if not os.path.exists(project_path):
        print(f"Путь {project_path} не существует")
        sys.exit(1)
    
    print(f"Анализ проекта: {project_path}")
    
    # Поиск проблем
    issues = find_session_issues(project_path)
    db_configs = analyze_database_config(project_path)
    
    # Генерация отчёта
    generate_report(issues, db_configs)
    generate_recommendations()
    
    # Сохранение детального отчёта
    with open('session_leak_report.txt', 'w', encoding='utf-8') as f:
        f.write("ДЕТАЛЬНЫЙ ОТЧЁТ О ПРОБЛЕМАХ С СЕССИЯМИ\n")
        f.write("=" * 50 + "\n\n")
        
        for issue in issues:
            f.write(f"Файл: {issue['file']}\n")
            f.write(f"Строка: {issue['line']}\n")
            f.write(f"Серьёзность: {issue['severity']}\n")
            f.write(f"Проблема: {issue['issue']}\n")
            f.write(f"Код: {issue['code']}\n")
            f.write("-" * 30 + "\n")
    
    print(f"\nДетальный отчёт сохранён в session_leak_report.txt")

if __name__ == "__main__":
    main()

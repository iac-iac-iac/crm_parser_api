# DataMaster Phone Collector

Парсер телефонных номеров клиентов через DataMaster API с поддержкой возобновления сбора и экспорта в CSV.

## Возможности

- ✅ Сбор телефонных номеров из проектов клиентов
- ✅ Нормализация номеров в международный формат (E.164)
- ✅ Дедупликация — каждый номер сохраняется один раз
- ✅ Возобновление прерванного сбора (State Manager)
- ✅ Экспорт данных в CSV (телефоны, статистика, клиенты)
- ✅ Подробное логирование всех операций
- ✅ Настраиваемые лимиты (клиенты/проекты/страницы)

## Установка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/iac-iac-iac/crm_parser_api.git
cd crm_parser_api

# Полный сбор всех клиентов
python main.py

# Тест на 10 клиентах
python main.py --limit-clients 10

# Ограничение по проектам и страницам
python main.py --limit-clients 5 --limit-projects 3 --max-pages 2
Возобновление прерванного сбора
bash
# Запустить сбор
python main.py --limit-clients 100

# Прервать через Ctrl+C

# Продолжить с того же места
python main.py --continue

# Экспортировать все отчёты
python main.py --export all

# Только телефоны
python main.py --export phones

# Статистика по запускам
python main.py --export runs

# Топ клиентов по количеству номеров
python main.py --export clients

# Телефоны последнего запуска
python main.py --export latest
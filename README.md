# road-safety-big-data
Групповой проект по дисциплине «Архитектура больших данных». Анализ ДТП в Великобритании.
# Анализ ДТП в Великобритании

Групповой проект по дисциплине «Архитектура больших данных».

Цель проекта — исследовать связь условий движения с тяжестью зарегистрированных ДТП, проверить три гипотезы и представить результаты на интерактивном дашборде.

## Участники

| Участник | Ответственность |
|---|---|
| Иван Ф | PostgreSQL, Docker и настройка окружения |
| Артём | ETL, подготовка и загрузка данных |
| Иван А | Анализ, статистические проверки и машинное обучение |
| Кира | Гипотезы, визуализация, дашборд и выводы |

## Данные

Используется открытый набор STATS19 Collisions.

Страница источника:
https://www.gov.uk/government/statistical-data-sets/road-safety-open-data

Исходный файл:

`dft-road-casualty-statistics-collision-1979-latest-published-year.csv`

Объём — приблизительно 1,5 ГБ.

Исходный CSV размещается локально:

`data/raw/dft-road-casualty-statistics-collision-1979-latest-published-year.csv`

CSV не включается в репозиторий. Для воспроизведения результатов используйте ту же версию набора. Точную ссылку скачивания и дату получения файла необходимо зафиксировать дополнительно.

## Архитектура

CSV → ETL на Python → PostgreSQL → анализ в Jupyter → визуализация в Superset.

PostgreSQL запускается в Docker. Данные БД сохраняются в Docker volume.

ETL обрабатывает полный CSV порциями по 100 000 строк и сохраняет восемь используемых столбцов за все годы.

Годовая статистика рассчитывается по всей таблице. Проверка гипотез и моделирование выполняются за 2022–2024 годы.

## Инструменты

- Python и Jupyter.
- Pandas, NumPy, SciPy и Scikit-learn.
- SQLAlchemy и Psycopg.
- PostgreSQL 17.
- Docker Desktop и Docker Compose.
- Apache Superset 6.0.0-dev.
- Matplotlib и Plotly.

## Гипотезы

1. Доля тяжёлых и смертельных ДТП на дорогах с ограничением 50–70 mph выше, чем на дорогах с ограничением 20–30 mph.
2. Доля тяжёлых и смертельных ДТП в темноте без освещения выше, чем при дневном свете.
3. В часы пик 07:00–09:59 и 16:00–18:59 регистрируется больше ДТП в расчёте на час, чем в остальные часы.

Дополнительно выполняются корреляционный анализ, описательная логистическая регрессия и классификация тяжести ДТП.

Модель классификации обучается на 2022–2023 годах и проверяется на 2024 году.

## 1. Подготовка Python

Установите Python, VS Code и Docker Desktop.

Откройте терминал в корне проекта и создайте окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pandas numpy scipy matplotlib scikit-learn sqlalchemy "psycopg[binary]" python-dotenv jupyterlab ipykernel plotly nbformat
```

Если окружение уже создано, активируйте его вместо повторного создания.

## 2. Настройка PostgreSQL

Создайте в корне проекта локальный файл `.env`:

```dotenv
POSTGRES_DB=road_safety
POSTGRES_USER=road_user
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_PORT=5432
```

Замените `CHANGE_ME` своим паролем до первого запуска БД.

Файл `.env` не добавляется в GitHub.

Запустите Docker Desktop, затем выполните:

```bash
docker compose up -d postgres
docker compose ps
```

Дождитесь статуса `healthy`.

Создайте таблицу:

```bash
docker compose exec -T postgres psql -U road_user -d road_safety -v ON_ERROR_STOP=1 < sql/schema.sql
```

Проверьте соединение:

```bash
docker compose exec postgres psql -U road_user -d road_safety -c "SELECT current_database(), current_user;"
```

## 3. Загрузка данных

Поместите исходный CSV в `data/raw/`.

Запустите:

```bash
python etl.py
```

Дождитесь сообщения «Загрузка завершена».

ETL проверяет идентификаторы, преобразует числовые поля, даты и время, затем загружает данные в PostgreSQL.

Совпадающие повторные записи пропускаются. Разные записи с одинаковым идентификатором останавливают загрузку и требуют разбора.

Отчёты сохраняются в `results/etl_report_*.json`. При наличии отклонённых записей создаются файлы `results/etl_rejects_*.csv`.

Проверка количества строк:

```bash
docker compose exec postgres psql -U road_user -d road_safety -c "SELECT COUNT(*) FROM public.collisions;"
```

## 4. Выполнение анализа

Откройте `analysis-2.ipynb` в VS Code.

1. Выберите ядро своего Python-окружения.
2. Убедитесь, что ETL завершён.
3. Перезапустите ядро.
4. Нажмите «Выполнить все».
5. Дождитесь завершения всех ячеек и сохраните ноутбук.

Ноутбук получает данные из PostgreSQL, проверяет гипотезы, обучает модель и создаёт представление `public.collisions_dashboard`.

Результаты сохраняются в `results/`:

- `quality.csv` — качество выборки.
- `hypotheses.csv` — результаты проверки гипотез.
- `regression.csv` — коэффициенты описательной регрессии.
- `correlations.csv` — корреляционные показатели.
- `ml_metrics.csv` — метрики классификации.
- `confusion_matrix.csv` — матрица ошибок.
- `conclusions.md` — выводы по выполненному анализу.
- `*_interactive.html` — интерактивные графики.
- `analysis_environment.json` — версии Python и библиотек.

## 5. Запуск Superset на Mac

Официальная конфигурация Superset скачивается в отдельную папку рядом с проектом.

```bash
cd ~/Projects
git clone --depth 1 --branch 6.0.0 https://github.com/apache/superset.git superset-tools
cd superset-tools
```

Если папка уже существует, перейдите в неё.

Сгенерируйте секретный ключ:

```bash
openssl rand -hex 42
```

Создайте файл `docker/.env-local` в папке Superset:

```dotenv
SUPERSET_SECRET_KEY=PASTE_GENERATED_KEY
SUPERSET_LOAD_EXAMPLES=no
```

Вместо `PASTE_GENERATED_KEY` вставьте сгенерированный ключ.

Запустите:

```bash
TAG=6.0.0-dev docker compose -f docker-compose-image-tag.yml up -d
```

Проверьте состояние:

```bash
TAG=6.0.0-dev docker compose -f docker-compose-image-tag.yml ps -a
```

Инициализация `superset-init` должна завершиться с кодом 0.

Откройте:

http://localhost:8088

Начальные данные входа стандартной локальной конфигурации:

- Логин — `admin`.
- Пароль — `admin`.

## 6. Подключение Superset к данным

В Superset откройте Settings → Database Connections → + Database → PostgreSQL.

Укажите:

| Параметр | Значение |
|---|---|
| Host | host.docker.internal |
| Port | 5432 или порт из `.env` проекта |
| Database | road_safety |
| Username | road_user |
| Password | Фактический пароль из `.env` проекта |

Эти параметры предназначены для Superset в отдельном Docker Compose на Mac.

Проверьте подключение и сохраните его под названием `Road Safety`.

Через Datasets добавьте представление:

`public.collisions_dashboard`

## 7. Дашборд

Дашборд «Анализ ДТП» включает:

- Количество ДТП по годам.
- Распределение ДТП по часам.
- Долю тяжёлых ДТП по ограничению скорости.
- Долю тяжёлых ДТП по освещению.
- Тепловую карту по дням недели и часам.

Для доли тяжёлых ДТП используется выражение:

```sql
100.0 * SUM(severe) / NULLIF(COUNT(severe), 0)
```

Фильтр года применяется к исследовательским графикам. Годовая динамика показывает весь исторический период.

После сборки дашборд экспортируется через меню Superset в ZIP.

Экспорт размещается в:

`superset/dashboard_export.zip`

На другом компьютере сначала настройте БД и загрузите данные. Затем импортируйте ZIP через раздел Dashboards и укажите пароль подключения, если Superset его запросит.

## 8. Повторный запуск

Запустите Docker Desktop.

В папке проекта:

```bash
docker compose up -d postgres
```

В папке Superset:

```bash
TAG=6.0.0-dev docker compose -f docker-compose-image-tag.yml up -d
```

Повторная загрузка CSV при сохранённой БД не требуется.

## Ограничения исследования

Набор содержит зарегистрированные полицией ДТП с пострадавшими.

Ограничение скорости отличается от фактической скорости автомобиля.

Без данных об интенсивности движения нельзя рассчитать риск ДТП на одну поездку.

Наблюдаемые зависимости не устанавливают причинность. Изменения методики регистрации ограничивают сравнение исторических периодов.

Метрики классификации относятся к тестовому периоду 2024 года.
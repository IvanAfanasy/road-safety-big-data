# Анализ ДТП — как запустить

Проект загружает данные ДТП в PostgreSQL, выполняет анализ в Jupyter и показывает готовый дашборд в Superset.

Первый запуск выполняется по шагам ниже. Для последующих запусков используйте последний раздел.

## 1. Установите программы и скачайте проект

Нужны Docker Desktop, Python 3.12 или 3.13, Git и VS Code. В VS Code установите расширения Python и Jupyter.

Откройте Docker Desktop и дождитесь его запуска.

В терминале выполните команды по очереди:

```bash
git clone https://github.com/IvanAfanasy/road-safety-big-data.git
cd road-safety-big-data
```

Если проект уже скачан, откройте его папку в VS Code и создайте терминал в этой папке.

## 2. Добавьте датасет и настройки

Возьмите у команды исходный файл `dft-road-casualty-statistics-collision-1979-latest-published-year.csv` объёмом около 1,5 ГБ. Положите его в папку проекта:

```text
data/raw/dft-road-casualty-statistics-collision-1979-latest-published-year.csv
```

Создайте рядом с `compose.yaml` файл `.env`:

```dotenv
POSTGRES_DB=road_safety
POSTGRES_USER=road_user
POSTGRES_PASSWORD=MyLocalPassword_2026
POSTGRES_PORT=5432
```

Пароль можно выбрать свой до первого запуска базы. Сохраните его для подключения Superset. Если база уже настроена, используйте существующий `.env`.

## 3. Подготовьте Python

На Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

На Windows в PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Если PowerShell запрещает активацию, разрешите её для текущего окна и повторите:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Затем установите библиотеки:

```bash
python -m pip install pandas numpy scipy matplotlib scikit-learn sqlalchemy "psycopg[binary]" python-dotenv jupyterlab ipykernel plotly nbformat
```

## 4. Запустите базу и загрузите данные

В терминале папки `road-safety-big-data`:

```bash
docker compose up -d postgres
docker compose ps
```

Дождитесь статуса `healthy` у PostgreSQL.

Создайте таблицу. Эти команды подходят для Mac и Windows:

```bash
docker compose cp sql/schema.sql postgres:/tmp/road_safety_schema.sql
docker compose exec postgres psql -U road_user -d road_safety -v ON_ERROR_STOP=1 -f /tmp/road_safety_schema.sql
```

Загрузите полный датасет:

```bash
python etl.py
```

Дождитесь сообщения **«Загрузка завершена»**. Не закрывайте Docker и терминал во время загрузки.

## 5. Выполните ноутбук

В VS Code откройте `analysis-2.ipynb`.

1. Справа сверху выберите ядро Python из созданной папки `.venv`.
2. Нажмите «Перезапустить», затем «Выполнить все».
3. Дождитесь завершения без ошибок и сохраните файл.

Результаты появятся в `results`. Ноутбук также создаст представление `collisions_dashboard`, которое нужно для дашборда.

## 6. Запустите Superset

Откройте второй терминал в папке проекта. Скачайте Superset в соседнюю папку:

```bash
cd ..
git clone --depth 1 --branch 6.0.0 https://github.com/apache/superset.git superset-tools
cd superset-tools
```

Если `superset-tools` уже существует, просто откройте терминал в ней.

Сгенерируйте ключ:

```bash
python -c "import secrets; print(secrets.token_hex(42))"
```

В папке `superset-tools/docker` создайте файл `.env-local`:

```dotenv
TAG=6.0.0-dev
SUPERSET_SECRET_KEY=ВСТАВЬТЕ_СГЕНЕРИРОВАННЫЙ_КЛЮЧ
SUPERSET_LOAD_EXAMPLES=no
```

Сохраните файл. Для существующей установки сохраняйте прежний секретный ключ.

Запустите Superset из папки `superset-tools`:

```bash
docker compose --env-file docker/.env-local -f docker-compose-image-tag.yml up -d
```

Проверьте:

```bash
docker compose --env-file docker/.env-local -f docker-compose-image-tag.yml ps -a
```

Дождитесь запуска основного сервиса `superset`. Статус `Exited (0)` у `superset-init` означает успешную инициализацию.

Откройте в браузере http://localhost:8088 и войдите с логином `admin` и паролем `admin`.

## 7. Импортируйте готовый дашборд

В Superset откройте **Dashboards** и нажмите **Import dashboard** — кнопку импорта со значком стрелки.

Выберите ZIP из корня скачанного проекта:

```text
dashboard_export_20261124T212929.zip
```

Если запрашивается пароль базы, введите `POSTGRES_PASSWORD` из вашего `.env` проекта. Завершите импорт.

Проверьте подключение через **Settings → Database Connections**. Для Docker Desktop на Mac и Windows используются:

| Поле | Значение |
|---|---|
| Host | `host.docker.internal` |
| Port | `5432` |
| Database | `road_safety` |
| Username | `road_user` |
| Password | Ваш пароль из `.env` проекта |

При другом порте укажите значение `POSTGRES_PORT`.

Откройте **Dashboards → Анализ ДТП**. Графики, расположение и фильтры восстанавливаются из ZIP. Выберите год и нажмите **Apply filters**, чтобы проверить работу.

Если импорт сообщает об ошибке структуры ZIP, используйте оригинальный архив экспорта Superset. Safari может автоматически распаковать его при скачивании.

## Как включать проект в следующий раз

1. Откройте Docker Desktop.
2. В терминале папки `road-safety-big-data` выполните:

```bash
docker compose up -d postgres
```

3. В терминале папки `superset-tools` выполните:

```bash
docker compose --env-file docker/.env-local -f docker-compose-image-tag.yml up -d
```

4. Откройте http://localhost:8088 → **Dashboards → Анализ ДТП**.

Данные, графики и настройки сохраняются между обычными перезапусками. Повторная загрузка CSV и импорт дашборда нужны при первоначальной настройке или обновлении. Ноутбук запускайте, когда нужны новые расчёты.

## Как выключать

Сохраните ноутбук и дашборд.

В папке `superset-tools`:

```bash
docker compose --env-file docker/.env-local -f docker-compose-image-tag.yml stop
```

В папке `road-safety-big-data`:

```bash
docker compose stop postgres
```

После этого можно закрыть Docker Desktop.

# Merkury

Один сервис `merkury_exporter.py` опрашивает счётчики и отдаёт метрики на `:9101/metrics`.
Prometheus их скрейпит и хранит историю, Grafana строит графики. sqlite остаётся суточным архивом.

| Файл | Назначение |
|---|---|
| `merkury_exporter.py` | опрос шлюза, метрики, запись в sqlite (замена `tst.py`, `prometheus_metrics.py`) |
| `report.py` | потребление с 28-го числа из sqlite (замена `chck_date_all*.py`) |
| `db.py` | схема, upsert, расчёт начала периода |
| `sn_list.json` | счётчики: `{"<sn>": {"coeff_trans": 80, "opisanie": "Имя"}}`, перечитывается каждый цикл |
| `test_merkury.py` | проверки на поддельном шлюзе |

## Запуск

```bash
pip install -r requirements.txt
python merkury_exporter.py
python report.py [--today 2026-09-24] [--day 28]
```

Настройки через env: `MERKURY_URL`, `MERKURY_DB`, `MERKURY_METERS`, `MERKURY_PORT` (9101),
`MERKURY_INTERVAL` (60 с), `MERKURY_TIMEOUT` (10 с), `MERKURY_TARIFFS` (`E1_1,E2_1`; добавь `E3_1,E4_1`, если тарифов больше двух).

systemd (`/etc/systemd/system/merkury.service`):

```ini
[Unit]
Description=Merkury exporter
After=network-online.target

[Service]
WorkingDirectory=/opt/merkury
ExecStart=/opt/merkury/.venv/bin/python merkury_exporter.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## Prometheus

```yaml
scrape_configs:
  - job_name: merkury
    scrape_interval: 60s
    static_configs:
      - targets: ['<хост-экспортера>:9101']
```

**Хранение:** по умолчанию Prometheus держит только 15 дней, для месячных расчётов запусти его с
`--storage.tsdb.retention.time=2y`.

## Метрики

`merkury_energy_kwh{sn,name}`, `merkury_period_kwh{sn,name}` (потребление с `MERKURY_PERIOD_DAY`-го числа, по умолчанию 28; база берётся из sqlite и не зависит от срока хранения Prometheus), `merkury_energy_tariff_kwh{sn,name,tariff}` (энергия × `coeff_trans`),
`merkury_voltage{sn,name,phase}`, `merkury_current{sn,name,phase}`,
`merkury_up`, `merkury_last_success_timestamp_seconds`, `merkury_poll_errors_total`.

## Запросы для Grafana

- **За расчётный период** (time range: с 28-го по сегодня, панель Stat/Table, тип запроса Instant):
  `merkury_energy_kwh - merkury_energy_kwh offset $__range`
- **По дням** (Min step = `1d`): `merkury_energy_kwh - merkury_energy_kwh offset 1d`.
  Границы суток при шаге 1d могут не совпадать с локальной полуночью.
- **Всё сразу по имени:** легенда `{{name}}`; новый счётчик в `sn_list.json` появляется без правок дашборда.
- **Алерты:** `merkury_up == 0`, `time() - merkury_last_success_timestamp_seconds > 600`

## Миграция

1. Остановить cron для `tst.py`, `prometheus_metrics.py`, `chck_date_all_for_prometheus.py`.
2. Удалить старые метрики из Pushgateway: `curl -X DELETE http://192.168.0.114:9091/metrics/job/merkury`.
3. Указать существующую базу: `MERKURY_DB=/путь/к/your_database.db`. При первом открытии схема получит
   `UNIQUE(sn, date)`; дубли (если были) схлопываются до последней строки.
4. Переписать запросы дашборда: `napr_na_1_faze<sn>` → `merkury_voltage{phase="1"}`, `tok_na_*` → `merkury_current`.
5. Убрать из репозитория: `chck_date_all.py`, `chck_date_all_for_prometheus.py`, `prometheus_metrics.py`,
   `tst.py`, `tempCodeRunnerFile.py`, `Pipfile*` (или `requirements.txt`), `*.prom`.

## Замечания

- Энергия в БД хранится сырой (без `coeff_trans`), как раньше; коэффициент применяется при выводе.
- Если накопленная энергия уменьшилась (сбой ответа, ноль), опрос считается неудачным и в БД не пишется.
  После физической замены счётчика перезапусти сервис.
- При ошибке опроса мгновенные U/I пропадают (серия stale), накопленная энергия остаётся, `merkury_up = 0`.
- `report.py` берёт базой запись за 28-е (суточная запись = последнее показание того дня), а формула Grafana
  берёт значение на начало выбранного диапазона. Цифры могут различаться на потребление в сам день 28-го.

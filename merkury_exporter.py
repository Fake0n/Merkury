#!/usr/bin/env python3
"""Опрашивает счётчики Меркурий и отдаёт их метрики на /metrics для Prometheus.

Заменяет tst.py, prometheus_metrics.py и chck_date_all*.py. Историю хранит Prometheus,
sqlite остаётся суточным архивом. Серийный номер и описание - labels, а не часть имени метрики.
"""
import json
import logging
import os
import signal
import threading
import time
from datetime import date, datetime

import requests
from prometheus_client import Counter, Gauge, start_http_server

import db

log = logging.getLogger("merkury")

# --- настройки (env) ---
GATEWAY_URL = os.environ.get("MERKURY_URL", "http://10.11.11.5/dist/install.php")
METERS_FILE = os.environ.get("MERKURY_METERS", os.path.join(db.HERE, "sn_list.json"))
DB_PATH = os.environ.get("MERKURY_DB", db.DEFAULT_DB)
PORT = int(os.environ.get("MERKURY_PORT", "9101"))
BIND = os.environ.get("MERKURY_BIND", "0.0.0.0")
INTERVAL = float(os.environ.get("MERKURY_INTERVAL", "60"))  # сек между циклами опроса
TIMEOUT = float(os.environ.get("MERKURY_TIMEOUT", "10"))    # сек на один запрос
# Какие тарифы входят в "общее потребление". По умолчанию как в старом коде (T1+T2).
TARIFFS = [k.strip() for k in os.environ.get("MERKURY_TARIFFS", "E1_1,E2_1").split(",") if k.strip()]
PERIOD_DAY = int(os.environ.get("MERKURY_PERIOD_DAY", "28"))  # день начала расчётного периода

KEYS = ['time', 'Ps', 'P1', 'P2', 'P3', 'Qs', 'Q1', 'Q2', 'Q3', 'Ss', 'S1', 'S2', 'S3',
        'U1', 'U2', 'U3', 'I1', 'I2', 'I3', 'Ks', 'K1', 'K2', 'K3', 'F1', 'F12', 'F13',
        'F23', 'E1_1', 'E2_1', 'E3_1', 'E4_1', 'SerialNumber']
ENERGY_KEYS = ['E1_1', 'E2_1', 'E3_1', 'E4_1']

# --- метрики ---
L = ["sn", "name"]
ENERGY = Gauge("merkury_energy_kwh", "Накопительная энергия (сумма MERKURY_TARIFFS) * coeff_trans", L)
PERIOD = Gauge("merkury_period_kwh",
               "Потребление с начала расчётного периода (база - суточная запись sqlite) * coeff_trans", L)
ENERGY_T = Gauge("merkury_energy_tariff_kwh", "Накопительная энергия по тарифу * coeff_trans", L + ["tariff"])
VOLT = Gauge("merkury_voltage", "Напряжение по фазе (как отдаёт прибор)", L + ["phase"])
CURR = Gauge("merkury_current", "Ток по фазе (как отдаёт прибор, без coeff_trans)", L + ["phase"])
UP = Gauge("merkury_up", "1 - последний опрос успешен", L)
LAST_OK = Gauge("merkury_last_success_timestamp_seconds", "Время последнего успешного опроса", L)
ERRORS = Counter("merkury_poll_errors", "Число неудачных опросов", L)


def load_meters(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse(text: str) -> dict:
    return dict(zip(KEYS, text.strip().split(";")))


def num(d: dict, key: str) -> float:
    v = d.get(key, "").strip()
    if not v:
        raise ValueError(f"нет поля {key}")
    return float(v)


def fetch(session: requests.Session, sn: str) -> dict:
    r = session.get(GATEWAY_URL, params={"action": "read_mydb_one", "sn": sn}, timeout=TIMEOUT)
    r.raise_for_status()
    d = parse(r.text)
    got = d.get("SerialNumber", "").replace("<br>", "").strip()  # шлюз дописывает <br> в конец ответа
    if got and got.lstrip("0") != sn.lstrip("0"):
        log.warning("%s: в ответе другой SerialNumber: %s", sn, got)
    return d


def drop_instant(sn: str, name: str) -> None:
    """При ошибке убираем мгновенные значения, чтобы серии стали stale, а не показывали старое."""
    for phase in ("1", "2", "3"):
        for g in (VOLT, CURR):
            try:
                g.remove(sn, name, phase)
            except KeyError:
                pass


def poll_meter(session, con, sn, meter, last_total, today) -> None:
    name = meter.get("opisanie", sn)
    coeff = float(meter.get("coeff_trans", 1))
    try:
        d = fetch(session, sn)
        total_raw = sum(num(d, k) for k in TARIFFS)
        prev = last_total.get(sn)
        if prev is not None and total_raw < prev - 0.001:
            # Накопительная энергия не убывает: это сбой ответа. После замены счётчика - перезапуск.
            raise ValueError(f"показание уменьшилось: {prev} -> {total_raw}")
        tariffs = {}
        for k in ENERGY_KEYS:
            try:
                tariffs[k] = num(d, k)
            except ValueError:
                pass
    except (requests.RequestException, ValueError) as e:
        log.warning("%s (%s): %s", sn, name, e)
        UP.labels(sn, name).set(0)
        ERRORS.labels(sn, name).inc()
        drop_instant(sn, name)
        return

    # Ниже - только запись, метрики обновляются целиком после успешного разбора.
    last_total[sn] = total_raw
    db.save_reading(con, sn, round(total_raw, 3), today)  # в БД сырое значение, как раньше
    ENERGY.labels(sn, name).set(total_raw * coeff)
    # Потребление за период считаем от записи в sqlite, поэтому оно не зависит от срока хранения Prometheus.
    base = db.base_reading(con, sn, db.period_start(date.fromisoformat(today), PERIOD_DAY))
    if base is None:
        try:
            PERIOD.remove(sn, name)
        except KeyError:
            pass
    else:
        PERIOD.labels(sn, name).set((total_raw - base) * coeff)
    for k, v in tariffs.items():
        ENERGY_T.labels(sn, name, k[1]).set(v * coeff)
    for phase in ("1", "2", "3"):
        for g, key in ((VOLT, f"U{phase}"), (CURR, f"I{phase}")):
            try:
                g.labels(sn, name, phase).set(num(d, key))
            except ValueError:
                try:
                    g.remove(sn, name, phase)
                except KeyError:
                    pass
    UP.labels(sn, name).set(1)
    LAST_OK.labels(sn, name).set(time.time())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    meters = load_meters(METERS_FILE)
    for sn, m in meters.items():
        UP.labels(sn, m.get("opisanie", sn)).set(0)
    con = db.open_db(DB_PATH)
    start_http_server(PORT, addr=BIND)
    log.info("метрики: http://%s:%d/metrics, счётчиков: %d, тарифы: %s", BIND, PORT, len(meters), TARIFFS)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    session = requests.Session()
    last_total: dict = {}
    while not stop.is_set():
        began = time.monotonic()
        try:
            meters = load_meters(METERS_FILE)  # новый прибор подхватывается без перезапуска
        except (OSError, ValueError) as e:
            log.error("не удалось перечитать %s, беру прежний список: %s", METERS_FILE, e)
        today = datetime.now().strftime("%Y-%m-%d")
        for sn, meter in meters.items():
            if stop.is_set():
                break
            poll_meter(session, con, sn, meter, last_total, today)
        stop.wait(max(0.0, INTERVAL - (time.monotonic() - began)))
    con.close()


if __name__ == "__main__":
    main()

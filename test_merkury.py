"""Проверки без реальных приборов: поддельный HTTP-шлюз + временная sqlite.

Запуск: python test_merkury.py   (нужны requests и prometheus-client)
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- поддельный шлюз: ответ по sn берётся из словаря ---
RESPONSES = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        sn = parse_qs(urlparse(self.path).query)["sn"][0]
        status, body = RESPONSES.get(sn, (404, ""))
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["MERKURY_URL"] = f"http://127.0.0.1:{server.server_port}/dist/install.php"

import requests  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402

import db  # noqa: E402
import merkury_exporter as ex  # noqa: E402


def body(sn, e1, e2, u=("230", "231", "229"), i=("1", "2", "3")):
    f = ["0"] * 32
    f[13:16], f[16:19] = u, i
    f[27], f[28], f[29], f[30], f[31] = str(e1), str(e2), "0", "0", sn
    return ";".join(f)


def sample(metric, **labels):
    return REGISTRY.get_sample_value(metric, labels)


def test_period_start():
    assert db.period_start(date(2026, 9, 24)) == date(2026, 8, 28)
    assert db.period_start(date(2026, 9, 28)) == date(2026, 9, 28)
    assert db.period_start(date(2026, 9, 30)) == date(2026, 9, 28)
    assert db.period_start(date(2026, 1, 5)) == date(2025, 12, 28)
    assert db.period_start(date(2026, 3, 1)) == date(2026, 2, 28)


def test_dedupe_and_upsert():
    with tempfile.TemporaryDirectory() as t:
        path = os.path.join(t, "x.db")
        c = sqlite3.connect(path)
        c.execute(db.SCHEMA)
        c.executemany("INSERT INTO result_data(sn,result_value,date) VALUES(?,?,?)",
                      [("1", 1.0, "2026-09-24"), ("1", 2.0, "2026-09-24")])
        c.commit(); c.close()
        con = db.open_db(path)
        assert con.execute("SELECT result_value FROM result_data").fetchall() == [(2.0,)]
        db.save_reading(con, "1", 5.0, "2026-09-24")
        assert con.execute("SELECT COUNT(*), MAX(result_value) FROM result_data").fetchone() == (1, 5.0)


def test_report_no_shift():
    # Старый zip() съезжал, если у одного счётчика не было записи за дату.
    with tempfile.TemporaryDirectory() as t:
        path = os.path.join(t, "x.db")
        con = db.open_db(path)
        for sn, v in (("A", 100), ("B", 200), ("C", 300)):
            db.save_reading(con, sn, v, "2026-08-28")
        db.save_reading(con, "A", 150, "2026-09-24")
        db.save_reading(con, "C", 380, "2026-09-24")  # у B сегодня нет записи
        con.close()
        meters = os.path.join(t, "m.json")
        json.dump({"A": {"coeff_trans": 2, "opisanie": "a"}, "B": {"coeff_trans": 1, "opisanie": "b"},
                   "C": {"coeff_trans": 1, "opisanie": "c"}, "D": {"coeff_trans": 1, "opisanie": "d"}},
                  open(meters, "w"))
        out = subprocess.run([sys.executable, os.path.join(HERE, "report.py"), "--db", path, "--meters", meters,
                              "--today", "2026-09-24"], capture_output=True, text=True, check=True).stdout
        assert "a: 100.00" in out, out
        assert "b: 0.00  [последнее показание 2026-08-28]" in out, out  # не съехало, устаревшее помечено
        assert "c: 80.00" in out, out
        assert "d: нет данных" in out, out


def test_exporter():
    with tempfile.TemporaryDirectory() as t:
        con = db.open_db(os.path.join(t, "x.db"))
        s, sess, last = "555", requests.Session(), {}
        meter = {"coeff_trans": 80, "opisanie": "T"}
        L = dict(sn=s, name="T")

        RESPONSES[s] = (200, body(s, 10.5, 4.5))
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 1
        assert sample("merkury_energy_kwh", **L) == 15.0 * 80
        assert sample("merkury_energy_tariff_kwh", tariff="1", **L) == 10.5 * 80
        assert sample("merkury_voltage", phase="2", **L) == 231
        assert con.execute("SELECT result_value FROM result_data WHERE sn=?", (s,)).fetchone() == (15.0,)
        assert sample("merkury_period_kwh", **L) is None               # базы на 28-е ещё нет

        RESPONSES[s] = (500, "")  # шлюз упал
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 0
        assert sample("merkury_voltage", phase="2", **L) is None      # мгновенные значения убраны
        assert sample("merkury_energy_kwh", **L) == 15.0 * 80          # энергия сохранена
        assert sample("merkury_poll_errors_total", **L) == 1

        RESPONSES[s] = (200, body(s, 0, 0))  # мусорный ноль не должен попасть ни в метрику, ни в БД
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 0
        assert sample("merkury_energy_kwh", **L) == 15.0 * 80
        assert con.execute("SELECT result_value FROM result_data WHERE sn=?", (s,)).fetchone() == (15.0,)

        RESPONSES[s] = (200, body(s, 11, 4.5, u=("230", "", "229")))  # пустое напряжение фазы 2
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 1
        assert sample("merkury_voltage", phase="2", **L) is None
        assert sample("merkury_voltage", phase="1", **L) == 230
        assert sample("merkury_energy_kwh", **L) == 15.5 * 80

        db.save_reading(con, s, 10.0, "2026-08-28")  # база периода: потребление = (15.5 - 10) * 80
        RESPONSES[s] = (200, body(s + "<br>", 11, 4.5))  # реальный шлюз дописывает <br>
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 1
        assert sample("merkury_period_kwh", **L) == 5.5 * 80
        ex.poll_meter(sess, con, s, meter, last, "2026-09-28")  # в сам день 28-го база = текущее показание
        assert sample("merkury_period_kwh", **L) == 0

        RESPONSES[s] = (200, "12;1;2")  # обрезанный ответ, нет энергии
        ex.poll_meter(sess, con, s, meter, last, "2026-09-24")
        assert sample("merkury_up", **L) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

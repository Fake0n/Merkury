#!/usr/bin/env python3
"""Потребление по счётчикам с 28-го числа (замена chck_date_all*.py).

Данные только читаются, ничего не сбрасывается. Счётчики сопоставляются по sn.
"""
import argparse
import json
import os
from datetime import date

from db import DEFAULT_DB, HERE, latest_readings, open_db, period_start


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.environ.get("MERKURY_DB", DEFAULT_DB))
    ap.add_argument("--meters", default=os.environ.get("MERKURY_METERS", os.path.join(HERE, "sn_list.json")))
    ap.add_argument("--day", type=int, default=28, help="день начала расчётного периода")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    args = ap.parse_args()

    with open(args.meters, encoding="utf-8") as f:
        meters = json.load(f)

    con = open_db(args.db)
    start = period_start(args.today, args.day)
    now = latest_readings(con, args.today)
    base = latest_readings(con, start)
    con.close()

    print(f"Период: {start} .. {args.today}")
    for sn, m in meters.items():
        name = m.get("opisanie", sn)
        if sn not in now or sn not in base:
            print(f"{name}: нет данных ({'нет текущего показания' if sn not in now else 'нет базы на ' + str(start)})")
            continue
        (v1, d1), (v0, d0) = now[sn], base[sn]
        kwh = (v1 - v0) * float(m.get("coeff_trans", 1))
        notes = []
        if d0 != start.isoformat():
            notes.append(f"база от {d0}")
        if d1 != args.today.isoformat():
            notes.append(f"последнее показание {d1}")
        if kwh < 0:
            notes.append("отрицательное: замена/сброс счётчика?")
        print(f"{name}: {kwh:.2f}" + (f"  [{'; '.join(notes)}]" if notes else ""))


if __name__ == "__main__":
    main()

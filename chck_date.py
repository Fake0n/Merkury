import sqlite3
from datetime import datetime, timedelta
import json


# Этот модуль:
#   - подключается к базе данных
#   - выбирает из базы данных значение по номеру счетчика,
#   - выводит показания конкретного счетчика за последний месяц с даты 28 числа прошлого месяца.
merkury_sn = '13082003'

with open ('sn_list.json','r') as file:
    merkury_data = json.load(file)

    # ределение 28 числа последнего месяца для вычета данных
today = datetime.now()
frst_day_this_month = today.replace(day=1)
last_month = frst_day_this_month - timedelta(days=1)
day_28_last_month = last_month.replace(day=28)
formatToday = today.strftime('%Y-%m-%d')
formatDay28 = day_28_last_month.strftime('%Y-%m-%d')

    # Подключенгие к ДБ с данными :
    # Выборка из колонки date значение сегодня.
con = sqlite3.connect('your_database.db')
cursorTD = con.cursor()
cursorTD.execute('SELECT sn, result_value, date FROM result_data WHERE date ==?', (f'{formatToday}',))
resultsTD = cursorTD.fetchall()

    # Выборка из колонки date значение 28 числа предыдущего месяца.
cursorD28 = con.cursor()
cursorD28.execute('SELECT sn, result_value, date FROM result_data WHERE date ==?', (f'{formatDay28}',))
resultsD28 = cursorD28.fetchall()
con.close()

    # Разбираем json файл из переменной merkury_data и осуществляем фильтрацию по значению счетчика
    # Первый for нужен для фильтрации счетчика в json, второй - для фильтрации данных из БД и сопоставляения
    # конкретного значения из json с конкретным значением из БД и при совпадении умножать на к.т. именно счетчика,
    # который указан в переменной merkury_sn.
for merkury, data in merkury_data.items():
    if merkury == merkury_sn:
        coef_trans = data["coeff_trans"]
        opisanie = data["opisanie"]

        for resultTD , resultD28 in zip(resultsTD,resultsD28) :
            if resultTD[0] == merkury_sn:
                print(opisanie,' : ',("%.2f" % ((resultTD[1] - resultD28[1]) * coef_trans)), sep='')

con.close()

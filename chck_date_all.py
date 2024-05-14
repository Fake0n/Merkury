import sqlite3
from datetime import datetime, timedelta
import json

# Этот модуль:
#   - подключается к базе данных
#   - выбирает из мазы данных все значения по очереди
#   - выводит потребление всех счетчиков за последний месяц с 28 числа пошлого месяца


    # Открываем json файл и добавляем в переменную merkury_data
with open('sn_list.json', 'r') as file:
    merkury_data = json.load(file)

    # Разделение 28 числа последнего месяца для вычета данных
today = datetime.now()
frst_day_this_month = today.replace(day=1)
last_month = frst_day_this_month - timedelta(days=1)
day_28_last_month = last_month.replace(day=28)
formatToday = today.strftime('%Y-%m-%d')
formatDay28 = day_28_last_month.strftime('%Y-%m-%d')

    # Подключение к ДБ с данными
con = sqlite3.connect('your_database.db')

    # Выборка из колонки date значения сегодня
cursorTD = con.cursor()
cursorTD.execute('SELECT sn, result_value, date FROM result_data WHERE date ==?', (f'{formatToday}',))
resultsTD = cursorTD.fetchall()

    # Выборка из колонки date значения 28 числа предыдущего месяца
cursorD28 = con.cursor()
cursorD28.execute('SELECT sn, result_value, date FROM result_data WHERE date ==?', (f'{formatDay28}',))
resultsD28 = cursorD28.fetchall()

    # Из файла json выбираем поочередно счетчик и каждый результат умножаем на нужный к.т. при совпадении
for merkury, data in merkury_data.items():
    sn = merkury
    coef_trans = data["coeff_trans"]
    opisanie = data["opisanie"]

    for resultTD , resultD28 in zip(resultsTD,resultsD28) :
        if resultTD[0] and resultD28[0] == merkury:
            print(opisanie,' : ',("%.2f" % ((resultTD[1] - resultD28[1]) * coef_trans)), sep='')

con.close()

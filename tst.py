import requests
import sqlite3
from datetime import datetime
import json


def create_tables(conn):
    cursor = conn.cursor()

    # Создание таблицы для данных
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS result_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sn TEXT NOT NULL,
            result_value REAL NOT NULL,
            date TEXT NOT NULL
        )
    ''')

    conn.commit()


def check_record_exists(conn, sn, current_date):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM result_data WHERE sn = ? AND date = ?", (sn, current_date))
    count = cursor.fetchone()[0]
    return count > 0


def update_or_insert_data(conn, sn, result_value, current_date):
    if check_record_exists(conn, sn, current_date):
        # Если запись существует, обновляем ее
        update_data(conn, sn, result_value, current_date)
    else:
        # Если запись не существует, создаем новую
        insert_data(conn, sn, result_value, current_date)


def update_data(conn, sn, result_value, current_date):
    cursor = conn.cursor()
    cursor.execute("UPDATE result_data SET result_value = ? WHERE sn = ? AND date = ?",
                   (result_value, sn, current_date))
    conn.commit()

    print(f"Данные для sn={sn} обновлены в базе данных.")


def insert_data(conn, sn, result_value, current_date):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO result_data (sn, result_value, date) VALUES (?, ?, ?)",
                   (sn, result_value, current_date))
    conn.commit()

    print(f"Создана новая запись для sn={sn} в базе данных.")


def main():
    # Чтение данных из файла
    with open ('sn_list.json','r') as file:
        merkury_json = json.load(file)
    #print(merkury_json)
    # Разделение текста и создание списка sn
    #sn_list = sn_list_text.split()


    # URL для GET-запроса
    url = "http://10.11.11.5/dist/install.php"

    # Параметры для подключения к базе данных SQLite
    db_path = "your_database.db"  # Укажите путь к базе данных
    conn = sqlite3.connect(db_path)

    # Создание таблиц, если они еще не созданы
    create_tables(conn)

    # Параметры запроса и обработка для каждого sn
    for sn in merkury_json:
        #print(sn)
        params = {
            'action': 'read_mydb_one',
            'sn': sn
        }
        #print(params)
        # Выполнение GET-запроса
        response = requests.get(url, params=params)

        # Проверка успешности запроса (код 200)
        if response.status_code == 200:
            # Разделение строки ответа на значения с помощью точки с запятой
            values = response.text.split(';')

            # Создание словаря с ключами и соответствующими значениями
            result_dict = {}
            for key, value in zip(['time', 'Ps', 'P1', 'P2', 'P3', 'Qs', 'Q1', 'Q2', 'Q3', 'Ss', 'S1', 'S2', 'S3',
                                   'U1', 'U2', 'U3', 'I1', 'I2', 'I3', 'Ks', 'K1', 'K2', 'K3', 'F1', 'F12', 'F13',
                                   'F23', 'E1_1', 'E2_1', 'E3_1', 'E4_1', 'SerialNumber'], values):
                result_dict[key] = value
            #print(result_dict)
            # Пример доступа к значениям по ключам
            result_value = round((float(result_dict['E1_1']) + float(result_dict['E2_1'])), 3)
            #print(result_value)

            # Обновление или создание данных в базе данных
            current_date = datetime.now().strftime("%Y-%m-%d")
            update_or_insert_data(conn, sn, result_value, current_date)
        else:
            # Если запрос неудачен, вывести сообщение об ошибке
            print(f"Error: Code {response.status_code}")

    # Закрытие соединения с базой данных
    conn.close()


if __name__ == "__main__":
    main()

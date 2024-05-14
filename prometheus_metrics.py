import requests
import json
import os

key_now = ['time', 'ps', 'p1', 'p2', 'p3', 'qs', 'q1', 'q2', 'q3', 'ss', 's1', 's2', 's3',
            'napr_na_1_faze', 'napr_na_2_faze', 'napr_na_3_faze', 'tok_na_1_faze', 'tok_na_2_faze', 'tok_na_3_faze', 'ks', 'k1', 'k2', 'k3', 'f1', 'f12', 'f13',
            'f23', 'e1_1', 'e2_1', 'e3_1', 'e4_1', 'SerialNumber']

# key_days = ['time', 'E11', 'E12', 'E13', 'E14', 'E21', 'E22', 'E23',
#             'E24', 'E31', 'E32', 'E33', 'E34', 'E41', 'E42', 'E43', 'E44', 'SerialNumber']

url_now = 'http://10.11.11.5/dist/install.php?action=read_mydb_one&sn='
#url_days = 'http://10.11.11.5/dist/install.php?action=read_energy_d&sn='

def get_data_now(sn, keys, url):
    url = f'{url}{sn}'
    request = requests.get(url)
    result = {}
    for key, value in zip(keys, request.text.split(';')):
        if (key == '' or key == 'napr_na_1_faze' or key == 'napr_na_2_faze' or key == 'napr_na_3_faze' or key == 'tok_na_1_faze' or key == 'tok_na_2_faze' or key == 'tok_na_3_faze'):
            result[key] = value
        resultProm = "\n".join([f'{key}{sn} {value}' for key, value in result.items()])
        resultProm += "\n"
    print(f"{sn} done!")
    with open (f'{sn}.prom', 'w') as prom_file:
        prom_file.write(resultProm)

with open ('sn_list.json','r') as json_file:
    data_json = json.load(json_file)
for sn in data_json:
    get_data_now(sn, key_now, url_now)

os.system('cat /root/Unost-energy/*.prom | curl -X POST --data-binary @- http://192.168.0.114:9091/metrics/job/merkury')
print("Bob's ur uncle!")
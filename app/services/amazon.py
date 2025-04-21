import time
from sp_api.api import Orders
from sp_api.base import Marketplaces

import logging
logging.basicConfig(level=logging.DEBUG)
from sp_api.auth import AccessTokenClient, Credentials


# Инициализация клиента
# orders_client = Orders(credentials=credentials, marketplace=Marketplaces.PL)
#
# response = orders_client.get_orders(CreatedAfter="2025-01-01")
# print(response.payload)

from sp_api.api import Reports
from sp_api.base.reportTypes import ReportType
from datetime import datetime, timedelta

# Инициализация клиента Reports
reports_client = Reports(credentials=credentials, marketplace=Marketplaces.PL)

# Укажите тип отчета и временной диапазон
# response = reports_client.create_report(
#     reportType=ReportType.GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL,  # Тип отчета
#     dataStartTime=(datetime.utcnow() - timedelta(days=30)).isoformat(),  # Начало месяца
#     dataEndTime=datetime.utcnow().isoformat()  # Конец месяца
# )

resp = reports_client.get_reports(reportTypes=["GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL"])
print(resp.payload)
# 
# Получение ID созданного отчета
report_id = '56524020187'
resp = reports_client.get_report(report_id)
print(resp.payload)
# print(f"Отчет создан. Report ID: {report_id}")
#
#
# while True:
#     status_response = reports_client.get_report(report_id)
#     status = status_response.payload.get('processingStatus')
#     print(f"Статус отчета: {status}")
#
#     if status == 'DONE':
#         print("Отчет готов!")
#         break
#     elif status in ['CANCELLED', 'FATAL']:
#         print("Ошибка при создании отчета.")
#         break
#
#     time.sleep(10)  # Подождите 10 секунд перед повторной проверкой
#
#
rep_doc_id = 'amzn1.spdoc.1.4.eu.ede76a99-fd6a-4b19-bee6-9acaf9fcd570.TRTZ5H8I4VJ0Y.2511'
report_document_response = reports_client.get_report_document(rep_doc_id)
url = report_document_response.payload.get('url')

# Скачивание файла
import requests

response = requests.get(url)
with open('monthly_report.csv', 'wb') as file:
    file.write(response.content)

print("Отчет успешно сохранен как 'monthly_report.csv'")

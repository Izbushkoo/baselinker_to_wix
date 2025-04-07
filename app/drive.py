import os

from google.oauth2 import service_account
from google.auth import default
from google.auth.impersonated_credentials import Credentials as ImpersonatedCredentials
from googleapiclient.discovery import build


SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = '../drive-api.json'

DELEGATED_USER = "info@tailwhip.store"


def imperson_auth():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
        subject="info@tailwhip.store"
    )

    service = build('drive', 'v3', credentials=creds)
    return service


def authenticate_service_account():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('drive', 'v3', credentials=creds)
    return service

def create_folder(service, name: str, parent_id: str = None) -> str:
    """
    Создаёт папку в Google Drive.
    :param service Авторизованный ресурс
    :param name: имя новой папки
    :param parent_id: (опционально) ID родительской папки, если нужно вложить
    :return: ID созданной папки
    """
    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
    }
    if parent_id:
        file_metadata['parents'] = [parent_id]

    folder = service.files().create(
        body=file_metadata,
        fields='id'
    ).execute()

    folder_id = folder.get('id')
    print(f'Создана папка "{name}", ID = {folder_id}')
    return folder_id


def list_folders(service):
    query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(
        q=query,
        pageSize=100,  # сколько вернуть за раз
        fields="nextPageToken, files(id, name)"
    ).execute()

    folders = results.get('files', [])
    if not folders:
        print("Папок не найдено.")
    else:
        for f in folders:
            print(f"{f['name']} (ID: {f['id']})")


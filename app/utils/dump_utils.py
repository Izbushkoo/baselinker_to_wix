import os
import tempfile
import subprocess
import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

def dump_and_upload_to_drive(
    service,
    database_url: str,
    backup_folder_name: str = "backup",
) -> str:
    """
    1) Убеждаемся, что в Drive есть папка backup (создаём, если нет).
    2) Очищаем её от всех файлов (permanent delete).
    3) Делаем pg_dump в custom-формате во временный файл.
    4) Загружаем этот файл в папку backup.
    Возвращает ID созданного файла в Drive.
    """
    # --- Шаг 1: найти или создать папку backup ---
    # Ищем папку по имени в корне
    q_folder = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{backup_folder_name}' "
        "and trashed=false"
    )
    resp = service.files().list(q=q_folder, fields="files(id,name)").execute()
    folders = resp.get('files', [])

    if folders:
        folder_id = folders[0]['id']
        # --- Шаг 2: очистить папку от файлов ---
        page_token = None
        while True:
            list_resp = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id)",
                pageToken=page_token
            ).execute()
            for f in list_resp.get('files', []):
                service.files().delete(
                    fileId=f['id'],
                    supportsAllDrives=True
                ).execute()
            page_token = list_resp.get('nextPageToken')
            if not page_token:
                break
    else:
        # создаём новую папку backup
        folder = service.files().create(
            body={
                'name': backup_folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            },
            fields='id'
        ).execute()
        folder_id = folder['id']

    # --- Шаг 3: делать дамп в временный файл ---
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"dump_{ts}.dump"
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }

    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
        tmp_path = tmp.name
        proc = subprocess.run(
            ["pg_dump", "--dbname", database_url, "--format", "custom"],
            stdout=tmp,
            stderr=subprocess.PIPE,
            text=True
        )
    if proc.returncode != 0:
        os.remove(tmp_path)
        raise RuntimeError(f"pg_dump failed: {proc.stderr.strip()}")

    # --- Шаг 4: залить дамп из временного файла ---
    with open(tmp_path, "rb") as fh:
        media = MediaIoBaseUpload(
            fh,
            mimetype="application/octet-stream",
            resumable=True
        )
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id"
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
        file_id = response["id"]

    # удаляем временный файл
    os.remove(tmp_path)

    print(f"Dump uploaded as {file_name} in folder '{backup_folder_name}', Drive file ID: {file_id}")
    return file_id

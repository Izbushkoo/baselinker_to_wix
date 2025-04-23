import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
import requests
import json
import time
import os

from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from app.database import SessionLocal
from app.core.config import settings
from app.models.allegro_token import AllegroToken
from app.services.allegro.data_access import update_token_by_id, update_token_by_id_sync, insert_token_sync, get_token_by_id_sync
from app.services.allegro.pydantic_models import InitializeAuth
from app.services.allegro.pydantic_models import InitializeAuth as SchemaInitializeAuth


CODE_URL = "https://allegro.pl/auth/oauth/device"
TOKEN_URL = "https://allegro.pl/auth/oauth/token"

ALLEGRO_AUTH_URL = "https://allegro.pl/auth/oauth/device"
ALLEGRO_TOKEN_URL = "https://allegro.pl/auth/oauth/token"

logger = logging.getLogger(__name__)


async def check_token(database: AsyncSession, token: AllegroToken) -> Optional[AllegroToken]:
    """
    Проверяет и при необходимости обновляет токен Allegro асинхронно.
    
    Args:
        database: Асинхронная сессия базы данных
        token: Токен для проверки
        
    Returns:
        Optional[AllegroToken]: Обновленный токен или None в случае ошибки
        
    Raises:
        Exception: Если токен недействителен
    """
    access_token = token.access_token
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/vnd.allegro.public.v1+json',
    }
    async with aiohttp.ClientSession() as session:
        async with session.get('https://api.allegro.pl/me', headers=headers) as res:
            if res.status == 200:
                logging.info('API call successful, token is valid')
                return token
            elif res.status == 401:
                logging.info('API call failed, token has expired, refreshing...')
                try:
                    new_access_token = await refresh_access_token(database, token)
                    logging.info('Access token refreshed successfully')
                    return new_access_token
                except Exception as err:
                    logging.error(f'Error refreshing access token: {err}')
                    raise
            else:
                logging.error(f'API call failed, token is invalid: {res.reason} {res.status}')
                raise Exception('Invalid access token')


async def refresh_access_token(database: AsyncSession, token: AllegroToken) -> AllegroToken:
    """
    Обновляет токен доступа асинхронно.
    
    Args:
        database: Асинхронная сессия базы данных
        token: Токен для обновления
        
    Returns:
        AllegroToken: Обновленный токен
        
    Raises:
        Exception: Если не удалось обновить токен
    """
    client_id = token.client_id
    client_secret = token.client_secret
    refresh_token = token.refresh_token

    auth_str = f'{client_id}:{client_secret}'
    b64_auth_str = base64.b64encode(auth_str.encode()).decode()
    headers = {
        'Authorization': f'Basic {b64_auth_str}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'redirect_uri': token.redirect_url
    }
    async with aiohttp.ClientSession() as session:
        async with session.post('https://allegro.pl/auth/oauth/token', headers=headers, data=data) as res:
            body = await res.json()
            if res.status == 200:
                access_token = body['access_token']
                refresh_token = body['refresh_token']
                logging.info('Access token refreshed successfully')
                try:
                    token = await update_token_by_id(
                        database=database,
                        token_id=token.id_,
                        refresh_token=refresh_token,
                        access_token=access_token
                    )
                    logging.info('New tokens saved to database successfully')
                    return token
                except Exception as error:
                    logging.error(f'Error saving new tokens to database: {error}')
                    raise Exception('Failed to save new tokens to database')
            else:
                logging.error(f"Error refreshing access token: {res.status} {res.reason}")
                raise Exception('Failed to refresh access token')


def refresh_access_token_sync(database: Session, token: AllegroToken) -> AllegroToken:
    """
    Обновляет токен доступа синхронно.
    
    Args:
        database: Сессия базы данных
        token: Токен для обновления
        
    Returns:
        AllegroToken: Обновленный токен
        
    Raises:
        Exception: Если не удалось обновить токен
    """
    client_id = token.client_id
    client_secret = token.client_secret
    refresh_token = token.refresh_token

    auth_str = f'{client_id}:{client_secret}'
    b64_auth_str = base64.b64encode(auth_str.encode()).decode()
    headers = {
        'Authorization': f'Basic {b64_auth_str}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'redirect_uri': token.redirect_url
    }

    res = requests.post('https://allegro.pl/auth/oauth/token', headers=headers, data=data)
    body = res.json()

    if res.status_code == 200:
        access_token = body['access_token']
        refresh_token = body['refresh_token']
        logging.info('Access token refreshed successfully')
        try:
            token = update_token_by_id_sync(
                database=database,
                token_id=token.id_,
                refresh_token=refresh_token,
                access_token=access_token
            )
            logging.info('New tokens saved to database successfully')
            return token
        except Exception as error:
            logging.error(f'Error saving new tokens to database: {error}')
            raise Exception('Failed to save new tokens to database')
    else:
        logging.error(f"Error refreshing access token: {res.status_code} {res.reason}")
        raise Exception('Failed to refresh access token')


def check_token_sync(token_id: str) -> Optional[Dict[str, Any]]:
    """
    Проверяет и при необходимости обновляет токен Allegro.
    
    Args:
        token_id: ID токена
        
    Returns:
        Optional[Dict[str, Any]]: Словарь с токенами или None в случае ошибки
    """
    with SessionLocal() as db:
        token = get_token_by_id_sync(db, token_id)
        if not token:
            return None
            
        # Проверяем токен через API запрос
        headers = {
            'Authorization': f'Bearer {token.access_token}',
            'Accept': 'application/vnd.allegro.public.v1+json',
        }
        
        try:
            response = requests.get('https://api.allegro.pl/me', headers=headers)
            if response.status_code == 200:
                logging.info('API call successful, token is valid')
                return {
                    'access_token': token.access_token,
                    'refresh_token': token.refresh_token
                }
            elif response.status_code == 401:
                logging.info('API call failed, token has expired, refreshing...')
                try:
                    # Обновляем токен
                    new_token = refresh_access_token_sync(db, token)
                    logging.info('Access token refreshed successfully')
                    return {
                        'access_token': new_token.access_token,
                        'refresh_token': new_token.refresh_token
                    }
                except Exception as err:
                    logging.error(f'Error refreshing access token: {err}')
                    return None
            else:
                logging.error(f'API call failed, token is invalid: {response.reason} {response.status_code}')
                return None
                
        except Exception as e:
            logging.error(f"Ошибка при проверке токена: {str(e)}")
            return None


def get_code(client_id: str, client_secret: str):
    payload = {'client_id': client_id}
    headers = {'Content-type': 'application/x-www-form-urlencoded'}
    api_call_response = requests.post(CODE_URL, auth=(client_id, client_secret),
                                      headers=headers, data=payload, verify=False)
    return api_call_response.json()


def get_access_token(device_code, init_auth: InitializeAuth):
    try:
        headers = {'Content-type': 'application/x-www-form-urlencoded'}
        data = {'grant_type': 'urn:ietf:params:oauth:grant-type:device_code', 'device_code': device_code}
        api_call_response = requests.post(TOKEN_URL, auth=(init_auth.client_id, init_auth.client_secret),
                                          headers=headers, data=data, verify=False)
        return api_call_response
    except requests.exceptions.HTTPError as err:
        raise err


def await_for_access_token(interval, device_code, init_auth: InitializeAuth):
    max_attempt = 30
    attempt = 0
    while attempt < max_attempt:
        time.sleep(interval)
        result_access_token = get_access_token(device_code, init_auth)
        token = json.loads(result_access_token.text)
        if result_access_token.status_code == 400:
            if token['error'] == 'slow_down':
                interval += interval
            if token['error'] == 'access_denied':
                break
            attempt += 1
        else:
            return token
    raise TimeoutError("too long wait till auth completed. Exited")


def initialize_auth(init_auth: InitializeAuth) -> Dict[str, Any]:
    """Initialize Allegro authentication with the provided credentials."""
    # Создаем сессию
    database = SessionLocal()
    try:
        code = get_code(init_auth.client_id, init_auth.client_secret)
        logging.info(f"{code}")
        logging.info(f"{type(code)}")
        token = await_for_access_token(int(code['interval']), code['device_code'], init_auth)
        allegro_token: AllegroToken = AllegroToken(
            belongs_to=init_auth.user_id,
            account_name=init_auth.account_name,
            description=init_auth.account_description,
            redirect_url="none",
            client_id=init_auth.client_id,
            client_secret=init_auth.client_secret,
            access_token=token["access_token"],
            refresh_token=token["refresh_token"]
        )
        insert_token_sync(database, allegro_token)
        logging.info(f"{allegro_token}")
        logging.info(f"Token successfully added to database")
        return allegro_token
    finally:
        database.close()


def initialize_device_flow(account_name: str) -> Dict:
    """
    Инициализирует процесс Device Flow авторизации для Allegro.
    
    Args:
        account_name: Имя аккаунта для идентификации токена
    
    Returns:
        Dict с данными авторизации (device_code, user_code, verification_uri, etc.)
    """
    client_id = os.getenv("ALLEGRO_CLIENT_ID")
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise ValueError("ALLEGRO_CLIENT_ID и ALLEGRO_CLIENT_SECRET должны быть установлены")
    
    try:
        response = requests.post(
            ALLEGRO_AUTH_URL,
            auth=(client_id, client_secret),
            data={"client_id": client_id}
        )
        response.raise_for_status()
        auth_data = response.json()
        auth_data["account_name"] = account_name
        return auth_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при инициализации Device Flow: {str(e)}")
        raise


def check_auth_status(device_code: str, account_name: str) -> str:
    """
    Проверяет статус авторизации для данного device_code.
    
    Args:
        device_code: Код устройства, полученный от initialize_device_flow
        account_name: Имя аккаунта для идентификации токена
    
    Returns:
        'pending', 'completed', или 'failed'
    """
    client_id = os.getenv("ALLEGRO_CLIENT_ID")
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET")
    
    try:
        response = requests.post(
            ALLEGRO_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code
            }
        )
        
        if response.status_code == 400:
            error = response.json().get("error")
            if error == "authorization_pending":
                return "pending"
            else:
                logger.error(f"Ошибка авторизации: {error}")
                return "failed"
        
        response.raise_for_status()
        token_data = response.json()
        
        # Сохраняем токен в базу данных
        token = AllegroToken(
            account_name=account_name,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            client_id=client_id,
            client_secret=client_secret,
            redirect_url="none"
        )
        
        with SessionLocal() as session:
            session.add(token)
            session.commit()
        
        return "completed"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при проверке статуса авторизации: {str(e)}")
        return "failed"


def refresh_token(account_name: str) -> Optional[AllegroToken]:
    """
    Обновляет токен для указанного аккаунта.
    
    Args:
        account_name: Имя аккаунта
    
    Returns:
        Обновленный токен или None в случае ошибки
    """
    client_id = os.getenv("ALLEGRO_CLIENT_ID")
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET")
    
    with SessionLocal() as session:
        token = session.exec(
            select(AllegroToken).where(AllegroToken.account_name == account_name)
        ).first()
        
        if not token:
            logger.error(f"Токен не найден для аккаунта {account_name}")
            return None
        
        try:
            response = requests.post(
                ALLEGRO_TOKEN_URL,
                auth=(client_id, client_secret),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token.refresh_token
                }
            )
            response.raise_for_status()
            token_data = response.json()
            
            token.access_token = token_data["access_token"]
            token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])
            session.add(token)
            session.commit()
            session.refresh(token)
            
            return token
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при обновлении токена: {str(e)}")
            return None


def get_token(account_name: str) -> Optional[AllegroToken]:
    """
    Получает действующий токен для указанного аккаунта.
    
    Args:
        account_name: Имя аккаунта
    
    Returns:
        Действующий токен или None, если токен не найден или не может быть обновлен
    """
    with SessionLocal() as session:
        token = session.exec(
            select(AllegroToken).where(AllegroToken.account_name == account_name)
        ).first()
        
        if not token:
            return None
        
        # Если токен истекает в течение 5 минут, обновляем его
        if token.expires_at <= datetime.now() + timedelta(minutes=5):
            return refresh_token(account_name)
        
        return token


import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
import requests
import json
import time

from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.core.config import settings
from app.models.allegro_token import AllegroToken
from app.services.allegro.data_access import update_token_by_id, update_token_by_id_sync, insert_token_sync, get_token_by_id_sync
from app.services.allegro.pydantic_models import InitializeAuth


CODE_URL = "https://allegro.pl/auth/oauth/device"
TOKEN_URL = "https://allegro.pl/auth/oauth/token"

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


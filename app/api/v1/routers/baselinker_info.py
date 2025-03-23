import logging
from typing import List

from fastapi import APIRouter
from fastapi.exceptions import HTTPException

from app.services import baselinker as BL
from app.core.security import decrypt_api_key
from app.schemas import baselinker_models
from app.services.baselinker import GetInventoryProductsListParameters
from app.celery_app import launch_processing

router = APIRouter()


@router.get("/inventories", response_model=List[baselinker_models.Inventory])
async def get_inventories(baselinker_api_key: str):
    """Получает список всех инвентарей."""
    bl_api_client = BL.BaseLinkerAPI(api_token=decrypt_api_key(baselinker_api_key))
    result = await bl_api_client.send_request(BL.BaseLinkerMethod.get_inventories)

    if result["status"] == "SUCCESS":
        invents = result.get("inventories", [])
        response = [baselinker_models.Inventory(**invent) for invent in invents]
        return response
    else:
        raise HTTPException(status_code=500, detail="Error during getting inventories from baselinker")

# @router.post("/products_list")
# async def get_inventory_products_list(baselinker_api_key: str, params: BL.GetInventoryProductsListParameters):
#
#     bl_api_client = BL.BaseLinkerAPI(api_token=baselinker_api_key)
#     all_products = []
#     page = 1  # Начинаем с первой страницы
#
#     while True:
#         # Устанавливаем текущую страницу в параметры запроса
#         params.page = page
#         logging.info(f"Запрашиваем страницу {page} с параметрами: {params}")
#
#         # Отправляем запрос
#         result = await bl_api_client.send_request(BL.BaseLinkerMethod.get_inventory_products_list, parameters=params)
#
#         # Логируем ответ
#         logging.info(f"Ответ от Baselinker (страница {page}): {result}")
#
#         if result["status"] != "SUCCESS":
#             raise HTTPException(status_code=500, detail=f"Ошибка при получении товаров: {result}")
#
#         products = result.get("products", {})
#         if not products:
#             break  # Если нет товаров — выходим из цикла
#
#         # Преобразуем продукты и добавляем в общий список
#         all_products.extend([baselinker_models.Product(**product) for product in products.values()])
#
#         # Если товаров меньше 1000, значит, больше страниц нет
#         if len(products) < 1000:
#             break
#         page += 1  # Переходим к следующей странице
#
#     return all_products
#
# @router.post("/product_ids_list")
# async def get_inventory_products_list(baselinker_api_key: str, params: BL.GetInventoryProductsListParameters):
#
#     bl_api_client = BL.BaseLinkerAPI(api_token=baselinker_api_key)
#     all_products = []
#     page = 1  # Начинаем с первой страницы
#
#     while True:
#         # Устанавливаем текущую страницу в параметры запроса
#         params.page = page
#         logging.info(f"Запрашиваем страницу {page} с параметрами: {params}")
#
#         # Отправляем запрос
#         result = await bl_api_client.send_request(BL.BaseLinkerMethod.get_inventory_products_list, parameters=params)
#
#         # Логируем ответ
#         logging.info(f"Ответ от Baselinker (страница {page}): {result}")
#
#         if result["status"] != "SUCCESS":
#             raise HTTPException(status_code=500, detail=f"Ошибка при получении товаров: {result}")
#
#         products = result.get("products", {})
#         if not products:
#             break  # Если нет товаров — выходим из цикла
#
#         # Преобразуем продукты и добавляем в общий список
#         all_products.extend([_id for _id in products.keys()])
#
#         # Если товаров меньше 1000, значит, больше страниц нет
#         if len(products) < 1000:
#             break
#         page += 1  # Переходим к следующей странице
#
#     return all_products


@router.post("/create_wix_import_file")
async def create_wix_import_file(baselinker_api_key: str, inventory_id: int, telegram_chat_id):
    decrypted_api_key = decrypt_api_key(baselinker_api_key)

    bl_api_client = BL.BaseLinkerAPI(api_token=decrypted_api_key)
    all_products = []
    page = 1  # Начинаем с первой страницы
    params = GetInventoryProductsListParameters(inventory_id=inventory_id)

    while True:
        # Устанавливаем текущую страницу в параметры запроса
        params.page = page
        logging.info(f"Запрашиваем страницу {page} с параметрами: {params}")

        # Отправляем запрос
        result = await bl_api_client.send_request(BL.BaseLinkerMethod.get_inventory_products_list, parameters=params)

        # Логируем ответ
        logging.info(f"Ответ от Baselinker (страница {page}): {result}")

        if result["status"] != "SUCCESS":
            raise HTTPException(status_code=500, detail=f"Ошибка при получении товаров: {result}")

        products = result.get("products", {})
        if not products:
            break  # Если нет товаров — выходим из цикла

        # Преобразуем продукты и добавляем в общий список
        all_products.extend([_id for _id in products.keys()])

        # Если товаров меньше 1000, значит, больше страниц нет
        if len(products) < 1000:
            break
        page += 1  # Переходим к следующей странице

    if not all_products:
        raise HTTPException(status_code=404, detail="Товары не найдены")

    logging.info(all_products)
    # Запускаем обработку товаров в фоне
    task_result = launch_processing(decrypted_api_key, inventory_id, all_products, telegram_chat_id)

    # Возвращаем task_id, чтобы можно было отслеживать статус, если потребуется
    return {"detail": "Процесс запущен", "task_id": task_result.id}






import requests
import json
from typing import List, Dict, Optional, Union, Any
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict, Field as PydanticField
from pprint import pprint


class ProductType(str, Enum):
    PHYSICAL = "physical"
    DIGITAL = "digital"


class DiscountType(str, Enum):
    NONE = "NONE"
    AMOUNT = "AMOUNT"
    PERCENT = "PERCENT"


# API Models
class WixMediaItem(SQLModel):
    """Модель медиа-элемента"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class WixMedia(SQLModel):
    """Модель медиа-данных"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    main_media: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)


class WixPriceData(SQLModel):
    """Модель цены товара для API"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    currency: str = Field(default="USD")
    price: float = Field(ge=0)
    discounted_price: Optional[float] = Field(default=None, ge=0)
    formatted: Optional[Dict[str, str]] = None


class WixStockData(SQLModel):
    """Модель данных о стоке для API"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    track_inventory: bool = Field(default=False)
    in_stock: bool = Field(default=True)
    quantity: Optional[int] = Field(default=None, ge=0)


class WixProductOption(SQLModel):
    """Модель опции товара для API"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    option_type: str = Field(default="drop_down")
    name: str
    choices: List[Dict[str, Union[str, bool]]] = Field(default_factory=list)


class WixProductAPI(SQLModel):
    """Модель товара Wix для работы с API"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    id: str
    name: str
    slug: Optional[str] = None
    visible: bool = Field(default=True)
    product_type: ProductType = Field(default=ProductType.PHYSICAL)
    description: Optional[str] = None
    sku: Optional[str] = None
    weight: float = Field(default=0.0, ge=0)
    stock: WixStockData = Field(default_factory=WixStockData)
    price: Optional[WixPriceData] = None
    price_data: Optional[WixPriceData] = None
    converted_price_data: Optional[WixPriceData] = None
    ribbon: Optional[str] = None
    brand: Optional[str] = None
    media: WixMedia = Field(default_factory=WixMedia)
    product_options: List[WixProductOption] = Field(default_factory=list)
    variants: List[Dict] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    discount: Dict[str, Union[DiscountType, float]] = Field(
        default_factory=lambda: {"type": DiscountType.NONE, "value": 0}
    )
    inventory_item_id: Optional[str] = Field(default=None, alias="inventoryItemId")


class WixProductUpdate(SQLModel):
    """Модель для обновления товара"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    name: Optional[str] = None
    product_type: Optional[ProductType] = None
    price_data: Optional[Dict[str, float]] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    visible: Optional[bool] = None
    weight: Optional[float] = None
    ribbon: Optional[str] = None
    brand: Optional[str] = None
    discount: Optional[Dict[str, Union[DiscountType, float]]] = None
    product_options: Optional[List[WixProductOption]] = None


class WixInventoryUpdate(SQLModel):
    """Модель для обновления стока"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    inventory_item_id: str = Field(alias="inventoryId")
    variant_id: Optional[str] = None
    quantity: int = Field(ge=0)


# DB Models (заготовка на будущее)
class WixProductDB(SQLModel, table=True):
    """Модель товара Wix для работы с БД (заготовка на будущее)"""
    __tablename__ = "wix_products"
    
    id: str = Field(primary_key=True)
    sku: Optional[str] = Field(index=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)
    last_sync_at: Optional[datetime] = None


class WixInventoryVariant(SQLModel):
    """Модель варианта товара в инвентаре"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    variant_id: str = Field(alias="variantId")
    in_stock: bool = Field(default=False, alias="inStock")
    quantity: Optional[int] = None
    available_for_preorder: Optional[bool] = Field(default=None, alias="availableForPreorder")

    @classmethod
    def from_dict(cls, data: Dict) -> "WixInventoryVariant":
        """Создание объекта из словаря с учетом алиасов"""
        return cls(
            variant_id=data["variantId"],
            in_stock=data.get("inStock", False),
            quantity=data.get("quantity"),
            available_for_preorder=data.get("availableForPreorder")
        )


class WixPreorderInfo(SQLModel):
    """Модель информации о предзаказе"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    enabled: bool = Field(default=False)
    message: Optional[str] = None

    def to_dict(self) -> Dict:
        """Преобразование объекта в словарь"""
        return self.model_dump(exclude_none=True)


class WixInventoryItem(SQLModel):
    """Модель элемента инвентаря"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    id: str
    external_id: Optional[str] = Field(default=None, alias="externalId")
    product_id: str = Field(alias="productId")
    track_quantity: bool = Field(default=True, alias="trackQuantity")
    variants: List[WixInventoryVariant] = Field(default_factory=list)  # Возвращаем тип WixInventoryVariant
    last_updated: Optional[datetime] = Field(default=None, alias="lastUpdated")
    numeric_id: Optional[str] = Field(default=None, alias="numericId")
    preorder_info: Optional[WixPreorderInfo] = Field(default=None, alias="preorderInfo")  # Возвращаем тип WixPreorderInfo


class WixInventoryMetadata(SQLModel):
    """Модель метаданных инвентаря"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    items: int
    offset: int


class WixInventoryResponse(SQLModel):
    """Модель ответа API инвентаря"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    inventory_items: List[Dict] = Field(alias="inventoryItems")  # Изменено на Dict для прямой валидации
    metadata: WixInventoryMetadata
    total_results: int = Field(alias="totalResults")


class WixInventoryQuery(SQLModel):
    """Модель запроса инвентаря"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    filter: Optional[str] = None
    sort: Optional[str] = None
    paging: Optional[Dict[str, int]] = None


class WixApiError(Exception):
    """Базовый класс для ошибок Wix API"""
    pass


class WixProductFilter(SQLModel):
    """Модель фильтра для товаров"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    sku_list: Optional[List[str]] = None
    product_ids: Optional[List[str]] = None
    visible: Optional[bool] = None
    product_type: Optional[ProductType] = None
    brand: Optional[str] = None
    custom_filter: Optional[Dict] = None  # Для дополнительных фильтров в формате API


class WixInventoryFilter(SQLModel):
    """Модель фильтра для инвентаря"""
    model_config = ConfigDict(from_attributes=True, extra="allow")
    
    product_ids: Optional[List[str]] = None
    sort: Optional[str] = None
    custom_filter: Optional[Dict] = None  # Для дополнительных фильтров в формате API


class WixApiService:
    def __init__(self):
        self.wix_api_key = "IST.eyJraWQiOiJQb3pIX2FDMiIsImFsZyI6IlJTMjU2In0.eyJkYXRhIjoie1wiaWRcIjpcImU1MWYxM2EwLTgxYTgtNDgxNS05Y2Q2LThjMjZlNDVmMjIwMFwiLFwiaWRlbnRpdHlcIjp7XCJ0eXBlXCI6XCJhcHBsaWNhdGlvblwiLFwiaWRcIjpcIjM3NzE1ZTdjLTkyMWYtNDcyMC1iZGE5LTI0OTU1NWI5NjM5NFwifSxcInRlbmFudFwiOntcInR5cGVcIjpcImFjY291bnRcIixcImlkXCI6XCJjMmM5MTllZC1iMWY5LTQwMzgtOTY4Ni1mZjA1YmNiY2RmMDhcIn19IiwiaWF0IjoxNzQ5NjM2MzEyfQ.VwQkWABD5yiu_HBmay0sCkpCg0ahFPAU-S_Y3zhzSE1rDLK9uWX2lqnY8EAaqjoJzy0iYJiy3KVg25fKpLlO6sTuRr7IuzFTX7xQXjDNuPhearsm9kaRxcFrZXzxr9Q_KQfnde8oBdhQZHa7ChT6BGZ32mHE1aFQpwnodoO4r6hCnSf3YyGGXCsoV5mdt8fgFJ677QHv7U52-09HyC0PGtaYqqbkwUTYQi1jG8QxPwiZWuT7QFB7POWtFGO0t-HizpZQkljQAzZGpeOLcrf3c5dTQnKneOYOAve3zeKbsV5aqnLMFnBGUh8edfzx1Cg99yMQ00X8f3YJ4OInyaBx9g"
        self.site_id = "75b93fc8-d16b-4511-a3cb-97b5291f8ea4"
        self.account_id = "e9efeafa-e196-4ed4-a42c-1153375d9ddd"
        self.base_url = "https://www.wixapis.com"
        self.headers = {
            "Authorization": self.wix_api_key,
            "Content-Type": "application/json",
            "wix-site-id": self.site_id,
        }

    def _make_request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict:
        """Базовый метод для выполнения запросов к API"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise WixApiError(f"Ошибка при выполнении запроса к Wix API: {str(e)}")

    def get_products_by_sku(self, sku_list: List[str], batch_size: int = 100) -> List[WixProductAPI]:
        """
        Получение товаров по списку SKU
        
        Args:
            sku_list: Список SKU для поиска
            batch_size: Размер пакета для запроса (максимум 100 по документации Wix)
            
        Returns:
            List[WixProductAPI]: Список найденных товаров
        """
        if not sku_list:
            return []

        all_products = []
        # Разбиваем список SKU на батчи
        for i in range(0, len(sku_list), batch_size):
            batch_sku = sku_list[i:i + batch_size]
            payload = {
                "query": {
                    "filter": json.dumps({
                        "sku": {"$in": batch_sku}
                    }),
                    "paging": {
                        "limit": batch_size
                    },
                    "includeVariants": True
                }
            }
            
            try:
                data = self._make_request("POST", "stores-reader/v1/products/query", payload)
                products = data.get("products", [])
                
                for product in products:
                    try:
                        wix_product = WixProductAPI(**product)
                        all_products.append(wix_product)
                    except Exception as e:
                        print(f"Ошибка при валидации товара {product.get('id')}: {str(e)}")
                        continue
                    
            except WixApiError as e:
                print(f"Ошибка при получении товаров для SKU {batch_sku}: {str(e)}")
                continue
                
        return all_products

    def update_product(self, product_id: str, update_data: WixProductUpdate) -> WixProductAPI:
        """
        Обновление данных товара
        
        Args:
            product_id: ID товара
            update_data: Данные для обновления
            
        Returns:
            WixProductAPI: Обновленный товар
        """
        payload = {"product": update_data.model_dump(exclude_none=True)}
        try:
            data = self._make_request("PATCH", f"stores/v1/products/{product_id}", payload)
            return WixProductAPI(**data["product"])
        except WixApiError as e:
            raise WixApiError(f"Ошибка при обновлении товара {product_id}: {str(e)}")

    def update_inventory(self, updates: List[WixInventoryUpdate], increment: bool = True) -> None:
        """
        Обновление стока товаров
        
        Args:
            updates: Список обновлений стока
            increment: True для увеличения стока, False для уменьшения
        """
        if not updates:
            return

        endpoint = "stores/v2/inventoryItems/increment" if increment else "stores/v2/inventoryItems/decrement"
        field_name = "incrementData" if increment else "decrementData"
        
        # Преобразуем данные в формат API
        update_data = []
        for update in updates:
            item = {
                "productId": update.inventory_item_id,
                "incrementBy" if increment else "decrementBy": update.quantity
            }
            if update.variant_id:
                item["variantId"] = update.variant_id
            update_data.append(item)
        full_update_data = {field_name: update_data}
        print(full_update_data)
        try:
            self._make_request("POST", endpoint, full_update_data)
        except WixApiError as e:
            raise WixApiError(f"Ошибка при обновлении стока: {str(e)}")

    def query_inventory(
        self,
        product_ids: Optional[List[str]] = None,
        filter_str: Optional[str] = None,
        sort_str: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict:
        """
        Получение информации об инвентаре товаров
        
        Args:
            product_ids: Список ID товаров для фильтрации
            filter_str: Строка фильтрации в формате JSON
            sort_str: Строка сортировки
            limit: Количество элементов на странице
            offset: Смещение для пагинации
        
        Returns:
            Dict: Ответ API с информацией об инвентаре
        """
        endpoint = "stores-reader/v2/inventoryItems/query"
        
        # Формируем фильтр
        filter_dict = {}
        if product_ids:
            filter_dict["productId"] = {"$in": product_ids}
        if filter_str:
            filter_dict.update(json.loads(filter_str))
        
        # Формируем запрос
        query = {
            "filter": json.dumps(filter_dict) if filter_dict else None,
            "sort": sort_str,
            "paging": {"limit": limit, "offset": offset}
        }
        
        try:
            response = self._make_request("POST", endpoint, {"query": query})
            return response
        except WixApiError as e:
            raise WixApiError(f"Ошибка при запросе инвентаря: {str(e)}")

    def _build_product_filter(self, filter_data: WixProductFilter) -> Dict:
        """
        Построение фильтра для запроса товаров
        
        Args:
            filter_data: Данные фильтра
            
        Returns:
            Dict: Фильтр в формате API
        """
        filter_dict = {}
        
        if filter_data.sku_list:
            filter_dict["sku"] = {"$in": filter_data.sku_list}
            
        if filter_data.product_ids:
            filter_dict["id"] = {"$in": filter_data.product_ids}
            
        if filter_data.visible is not None:
            filter_dict["visible"] = filter_data.visible
            
        if filter_data.product_type:
            filter_dict["productType"] = filter_data.product_type
            
        if filter_data.brand:
            filter_dict["brand"] = filter_data.brand
            
        if filter_data.custom_filter:
            filter_dict.update(filter_data.custom_filter)
            
        return filter_dict

    def _build_inventory_filter(self, filter_data: WixInventoryFilter) -> Dict:
        """
        Построение фильтра для запроса инвентаря
        
        Args:
            filter_data: Данные фильтра
            
        Returns:
            Dict: Фильтр в формате API
        """
        filter_dict = {}
        
        if filter_data.product_ids:
            filter_dict["productId"] = {"$in": filter_data.product_ids}
            
        if filter_data.sort is not None:
            filter_dict["sort"] = filter_data.sort
            
            
        if filter_data.custom_filter:
            filter_dict.update(filter_data.custom_filter)
            
        return filter_dict

    def get_all_products(
        self,
        filter_data: Optional[WixProductFilter] = None,
        include_variants: bool = True
    ) -> List[WixProductAPI]:
        """
        Получение всех товаров из магазина с учетом ограничений API и фильтров
        
        Args:
            filter_data: Данные для фильтрации товаров
            include_variants: Включать ли варианты товаров в ответ
            
        Returns:
            List[WixProductAPI]: Список всех товаров, соответствующих фильтру
        """
        all_products = []
        offset = 0
        limit = 100  # Максимальный размер страницы по API
        
        # Формируем фильтр
        filter_dict = self._build_product_filter(filter_data) if filter_data else {}
        
        while True:
            payload = {
                "query": {
                    "filter": json.dumps(filter_dict) if filter_dict else None,
                    "paging": {
                        "limit": limit,
                        "offset": offset
                    },
                    "includeVariants": include_variants
                }
            }
            try:
                data = self._make_request("POST", "stores-reader/v1/products/query", payload)
                products = data.get("products", [])
                
                if not products:
                    break
                    
                for product in products:
                    try:
                        wix_product = WixProductAPI(**product)
                        all_products.append(wix_product)
                    except Exception as e:
                        print(f"Ошибка при валидации товара {product.get('id')}: {str(e)}")
                        continue
                
                # Если получили меньше товаров чем лимит, значит это последняя страница
                if len(products) < limit:
                    break
                    
                offset += limit
                
            except WixApiError as e:
                print(f"Ошибка при получении товаров (offset={offset}): {str(e)}")
                break
                
        return all_products

    def get_all_inventory_items(
        self,
        filter_data: Optional[WixInventoryFilter] = None
    ) -> List[WixInventoryItem]:
        """
        Получение всех инвентарей из магазина с учетом ограничений API и фильтров
        
        Args:
            filter_data: Данные для фильтрации инвентаря
            
        Returns:
            List[WixInventoryItem]: Список всех инвентарей, соответствующих фильтру
        """
        all_items = []
        offset = 0
        limit = 100  # Максимальный размер страницы по API
        
        # Формируем фильтр
        filter_dict = self._build_inventory_filter(filter_data) if filter_data else None
        print("Применяем фильтр:", filter_dict)
        
        while True:
            try:
                response = self.query_inventory(
                    filter_str=json.dumps(filter_dict) if filter_dict else None,
                    limit=limit,
                    offset=offset
                )
                
                # Получаем элементы инвентаря напрямую из ответа
                items = response.get("inventoryItems", [])
                if not items:
                    break
                
                # Преобразуем каждый элемент в модель
                for item_data in items:
                    try:
                        # Преобразуем варианты
                        variants = []
                        for variant_data in item_data.get("variants", []):
                            try:
                                variant = WixInventoryVariant.from_dict(variant_data)
                                variants.append(variant)
                            except Exception as e:
                                print(f"Ошибка при валидации варианта: {str(e)}")
                                print("Данные варианта:", json.dumps(variant_data, indent=2))
                                continue
                        
                        # Преобразуем preorder_info
                        preorder_info = None
                        if "preorderInfo" in item_data:
                            try:
                                preorder_info = WixPreorderInfo(**item_data["preorderInfo"])
                            except Exception as e:
                                print(f"Ошибка при валидации preorderInfo: {str(e)}")
                                print("Данные preorderInfo:", json.dumps(item_data["preorderInfo"], indent=2))
                        
                        # Создаем элемент инвентаря
                        inventory_item = WixInventoryItem(
                            id=item_data["id"],
                            external_id=item_data.get("externalId"),
                            product_id=item_data["productId"],
                            track_quantity=item_data.get("trackQuantity", True),
                            variants=variants,
                            last_updated=item_data.get("lastUpdated"),
                            numeric_id=item_data.get("numericId"),
                            preorder_info=preorder_info
                        )
                        all_items.append(inventory_item)
                    except Exception as e:
                        print(f"Ошибка при валидации элемента инвентаря {item_data.get('id')}: {str(e)}")
                        print("Данные элемента:", json.dumps(item_data, indent=2))
                        continue
                
                # Если получили меньше элементов чем лимит, значит это последняя страница
                if len(items) < limit:
                    break
                    
                offset += limit
                
            except WixApiError as e:
                print(f"Ошибка при получении инвентарей (offset={offset}): {str(e)}")
                break
                
        return all_items



# Пример использования
if __name__ == "__main__":
    service = WixApiService()
    
    # Пример получения товаров с фильтрацией
    try:
        print("\nПолучение товаров с фильтрацией...")
        product_filter = WixProductFilter(
            sku_list=["8858849103893_10g", "8850348117043_35g"],
            visible=True,
            product_type=ProductType.PHYSICAL
        )
        filtered_products = service.get_all_products(filter_data=product_filter)
        print(f"Получено товаров по фильтру: {len(filtered_products)}")
        if filtered_products:
            print("ID найденных товаров:", " ".join(p.id for p in filtered_products))
        
        print("\nПолучение инвентарей с фильтрацией...")
        inventory_filter = WixInventoryFilter(
            product_ids=[p.id for p in filtered_products] if filtered_products else None
        )
        filtered_inventory = service.get_all_inventory_items(filter_data=inventory_filter)
        print(f"Получено инвентарей по фильтру: {len(filtered_inventory)}")
        if filtered_inventory:
            print("\nДетали инвентарей:")
            for item in filtered_inventory:
                print(f"\nID: {item.id}")
                print(f"Product ID: {item.product_id}")
                print(f"Track Quantity: {item.track_quantity}")
                print(f"Last Updated: {item.last_updated}")
                print("Варианты:")
                for variant in item.variants:
                    print(f"  - Variant ID: {variant.variant_id}")
                    print(f"    В наличии: {variant.in_stock}")
                    print(f"    Количество: {variant.quantity}")
        
    except WixApiError as e:
        print(f"Ошибка: {str(e)}")



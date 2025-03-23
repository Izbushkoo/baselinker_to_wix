import datetime
import requests
import json
from enum import Enum
from typing import Optional, Union, List

import aiohttp
from fastapi import HTTPException

from pydantic import BaseModel, Field, EmailStr, field_validator



class BaseLinkerMethod(Enum):
    get_orders = "getOrders"
    add_invoice = "addInvoice"
    set_order_fields = "setOrderFields"
    get_inventories = "getInventories"
    get_inventory_products_list = "getInventoryProductsList"
    get_inventory_product_data = "getInventoryProductsData"


class MethodParameters(BaseModel):
    def as_params(self):
        return json.dumps(self.model_dump(exclude_none=True))


class GetOrdersParams(MethodParameters):
    order_id: Optional[int] = None
    date_confirmed_from: Optional[int] = Field(default=None)
    date_from: Optional[int] = Field(default=None)
    id_from: Optional[int] = None
    get_unconfirmed_orders: Optional[bool] = Field(default=False)
    include_custom_extra_fields: Optional[bool] = Field(default=False)
    status_id: Optional[int] = None
    filter_email: Optional[EmailStr] = None
    filter_order_source: Optional[str] = Field(default="amazon")
    filter_order_source_id: Optional[int] = None


class AddInvoiceParams(MethodParameters):
    order_id: int
    series_id: int
    vat_rate: Optional[Union[str, int, float]] = None


class SetOrderFieldsParams(MethodParameters):
    order_id: int
    invoice_fullname: Optional[str] = Field(max_length=200)
    invoice_company: Optional[str] = Field(max_length=200)
    invoice_address: Optional[str] = Field(max_length=250)
    invoice_nip: Optional[str] = Field(max_length=100)
    invoice_postcode: Optional[str] = Field(max_length=20)
    invoice_city: Optional[str] = Field(max_length=100)
    invoice_state: Optional[str] = Field(max_length=20)
    invoice_country: Optional[str] = Field(max_length=50)
    invoice_country_code: Optional[str] = Field(max_length=2)


class GetInventoryProductsListParameters(MethodParameters):
    inventory_id: int
    filter_id: Optional[int] = None
    filter_category_id: Optional[int] = None
    filter_ean: Optional[str] = Field(default=None, max_length=32)
    filter_sku: Optional[str] = Field(default=None, max_length=50)
    filter_name: Optional[str] = Field(default=None, max_length=200)
    filter_price_from: Optional[float] = None
    filter_price_to: Optional[float] = None
    filter_stock_from: Optional[int] = None
    filter_stock_to: Optional[int] = None
    page: Optional[int] = None
    filter_sort: Optional[str] = Field(default=None, max_length=30)


class GetInventoryProductsData(MethodParameters):
    inventory_id: int
    products: List[int]
    include_erp_units: Optional[bool] = Field(default=None)
    include_wms_units: Optional[bool] = Field(default=None)
    include_additional_eans: Optional[bool] = Field(default=None)



class BaseLinkerAPI:

    _BASE_URL = "https://api.baselinker.com/connector.php"

    def __init__(self, api_token: str):
        self._api_token = api_token

    async def send_request(self, method: BaseLinkerMethod, parameters: MethodParameters = None):
        headers = {
            "X-BLToken": self._api_token
        }
        data = {
            "method": method.value,
        }
        if parameters:
            data.update({
                "parameters": parameters.as_params()
            })

        async with aiohttp.ClientSession() as session:
            async with session.post(url=self._BASE_URL, headers=headers, data=data) as response:
                if response.status == 200:
                    return await response.json()

                raise HTTPException(status_code=response.status)

    def send_request_sync(self, method: BaseLinkerMethod, parameters: MethodParameters = None):
        """Синхронный метод, использующий requests"""
        headers = {
            "X-BLToken": self._api_token
        }
        data = {
            "method": method.value,
        }
        if parameters:
            data["parameters"] = parameters.as_params()

        response = requests.post(self._BASE_URL, headers=headers, data=data)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code)



if __name__ == "__main__":
    inst = GetOrdersParams(date_from="12-12-2023")
    print(inst)
    # print(inst.as_params())

from typing import Optional, Dict

import requests


class WixApiService:
    def __init__(self):
        self.wix_api_key = "IST.eyJraWQiOiJQb3pIX2FDMiIsImFsZyI6IlJTMjU2In0.eyJkYXRhIjoie1wiaWRcIjpcImU1MWYxM2EwLTgxYTgtNDgxNS05Y2Q2LThjMjZlNDVmMjIwMFwiLFwiaWRlbnRpdHlcIjp7XCJ0eXBlXCI6XCJhcHBsaWNhdGlvblwiLFwiaWRcIjpcIjM3NzE1ZTdjLTkyMWYtNDcyMC1iZGE5LTI0OTU1NWI5NjM5NFwifSxcInRlbmFudFwiOntcInR5cGVcIjpcImFjY291bnRcIixcImlkXCI6XCJjMmM5MTllZC1iMWY5LTQwMzgtOTY4Ni1mZjA1YmNiY2RmMDhcIn19IiwiaWF0IjoxNzQ5NjM2MzEyfQ.VwQkWABD5yiu_HBmay0sCkpCg0ahFPAU-S_Y3zhzSE1rDLK9uWX2lqnY8EAaqjoJzy0iYJiy3KVg25fKpLlO6sTuRr7IuzFTX7xQXjDNuPhearsm9kaRxcFrZXzxr9Q_KQfnde8oBdhQZHa7ChT6BGZ32mHE1aFQpwnodoO4r6hCnSf3YyGGXCsoV5mdt8fgFJ677QHv7U52-09HyC0PGtaYqqbkwUTYQi1jG8QxPwiZWuT7QFB7POWtFGO0t-HizpZQkljQAzZGpeOLcrf3c5dTQnKneOYOAve3zeKbsV5aqnLMFnBGUh8edfzx1Cg99yMQ00X8f3YJ4OInyaBx9g"
        self.site_id = "25018001-094d-43c7-a6fe-ff8f5f346b80"
        self.account_id = "c2c919ed-b1f9-4038-9686-ff05bcbcdf08"
        self.base_url = "https://www.wixapis.com"
        self.headers = {
            "Authorization": self.wix_api_key,
            "Content-Type": "application/json",
            "wix-site-id": self.site_id,
        }

    def make_request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict:
        """Базовый метод для выполнения запросов к API"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, json=payload)
            print(response.text)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Ошибка при выполнении запроса к Wix API: {str(e)}")



if __name__ == "__main__":

    client = WixApiService()
    cart = client.make_request("get", "ecom/v1/carts/current")
    print(cart)
    # res = client.make_request("get", "ecom/v1/checkouts/287dd709-ca86-4614-aaba-0b292a7762bf")
    # print(res)
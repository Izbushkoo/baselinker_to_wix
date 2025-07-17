import requests
from decimal import Decimal, ROUND_HALF_UP

class NBPClient:
    """
    Клиент для получения курсов PLN → целевая валюта
    через открытый API Национального банка Польши.
    """

    BASE_URL = "https://api.nbp.pl/api/exchangerates/rates/A/{currency}/?format=json"

    @classmethod
    def get_rate(cls, target_currency: str) -> Decimal:
        """
        Запрашивает средний курс (mid) из PLN в target_currency.
        
        :param target_currency: трехбуквенный ISO‑код валюты (например, 'CHF', 'EUR', 'USD')
        :return: курс Decimal, означающий 1 единица target_currency = X PLN
        :raises: requests.HTTPError, KeyError
        """
        url = cls.BASE_URL.format(currency=target_currency.upper())
        resp = requests.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()

        data = resp.json()
        # В ответе rates — список, берем первый элемент и его поле mid
        mid_rate = data["rates"][0]["mid"]
        return Decimal(str(mid_rate))

    @classmethod
    def convert(cls, amount_pln: Decimal, target_currency: str, 
                quantize_places: int = 2) -> Decimal:
        """
        Переводит указанную сумму в злотых (PLN) в целевую валюту.
        
        :param amount_pln: сумма в PLN (Decimal)
        :param target_currency: ISO‑код целевой валюты
        :param quantize_places: сколько знаков после запятой оставить в результате
        :return: сумма в target_currency, округлённая по HALF_UP
        """
        rate = cls.get_rate(target_currency)  # PLN per 1 target_currency
        # Чтобы получить, сколько target_currency будет за amount_pln:
        # amount_target = amount_pln / rate
        amount_target = (amount_pln / rate).quantize(
            Decimal(f"1.{'0'*quantize_places}"), 
            rounding=ROUND_HALF_UP
        )
        return amount_target


# === Пример использования ===
if __name__ == "__main__":
    from decimal import Decimal
    
    client = NBPClient()
    
    # Получаем курс CHF: 1 CHF = X PLN
    rate_chf = client.get_rate("CHF")
    print(f"1 CHF = {rate_chf} PLN")
    
    # Пересчитываем 70 PLN → CHF
    amount_pln = Decimal("70.00")
    chf = client.convert(70, "CHF")
    print(f"{amount_pln} PLN = {chf} CHF")
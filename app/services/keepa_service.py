import keepa
import os
from dotenv import load_dotenv

load_dotenv()


access_key = os.getenv("KEEPA_ACCESS_KEY")

api = keepa.Keepa(access_key)

result = api.query(domain="DE", items=["8720181213878"], product_code_is_asin=False)
for item in result:
    for k, v in item.items():
        print(f"key: {k}")
        print(f"value: {v}")
# print(result[0].keys())
# print(keepa.parse_csv(result))
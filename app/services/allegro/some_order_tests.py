import json
import requests


base_url = "https://api.allegro.pl/"
token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX25hbWUiOiIxMDI3NTgyODAiLCJzY29wZSI6WyJhbGxlZ3JvOmFwaTpvcmRlcnM6cmVhZCIsImFsbGVncm86YXBpOmZ1bGZpbGxtZW50OnJlYWQiLCJhbGxlZ3JvOmFwaTpwcm9maWxlOndyaXRlIiwiYWxsZWdybzphcGk6c2FsZTpvZmZlcnM6d3JpdGUiLCJhbGxlZ3JvOmFwaTpmdWxmaWxsbWVudDp3cml0ZSIsImFsbGVncm86YXBpOmJpbGxpbmc6cmVhZCIsImFsbGVncm86YXBpOmNhbXBhaWducyIsImFsbGVncm86YXBpOmRpc3B1dGVzIiwiYWxsZWdybzphcGk6c2FsZTpvZmZlcnM6cmVhZCIsImFsbGVncm86YXBpOnNoaXBtZW50czp3cml0ZSIsImFsbGVncm86YXBpOmJpZHMiLCJhbGxlZ3JvOmFwaTpvcmRlcnM6d3JpdGUiLCJhbGxlZ3JvOmFwaTphZHMiLCJhbGxlZ3JvOmFwaTpwYXltZW50czp3cml0ZSIsImFsbGVncm86YXBpOnNhbGU6c2V0dGluZ3M6d3JpdGUiLCJhbGxlZ3JvOmFwaTpwcm9maWxlOnJlYWQiLCJhbGxlZ3JvOmFwaTpyYXRpbmdzIiwiYWxsZWdybzphcGk6c2FsZTpzZXR0aW5nczpyZWFkIiwiYWxsZWdybzphcGk6cGF5bWVudHM6cmVhZCIsImFsbGVncm86YXBpOnNoaXBtZW50czpyZWFkIiwiYWxsZWdybzphcGk6bWVzc2FnaW5nIl0sImFsbGVncm9fYXBpIjp0cnVlLCJpc3MiOiJodHRwczovL2FsbGVncm8ucGwiLCJleHAiOjE3NDIxNzY3OTEsImp0aSI6IjAwNDgxOGE5LTFmYjMtNDk5Mi05ZmY5LTVjMjY2NDAwYzkxZSIsImNsaWVudF9pZCI6ImJkZDRkYTA1MThkOTQ5YzRiMDkxYTZhYmU0ZmQ4M2Y3In0.EyZHQEVHygtfcACnLM3AugE4s0YQLOLZVpIqxwXu8It1aOt5j8WS6F_TaGY8RfcBlRwWT2UJtZYkIq_j4NqivxFxL1cMWNARHwADvtBfNySgnQ_TWcrrzU3RxL0WSnvsJeIAGsyaztrwTIOqPzHm-JEbUaNmqKG32qRjgT9hwY4RStvUg5KOSpstjCelU_cxgGA2f9gOZADOurBEQoPBt-uPct9AAveaQ2nMRzNHnAwQ9j_-irfxl-rTfoW9aR1o7oUaTSieRAdbp0dwFQVfzXRv9LtfcYVwva14EcGylrqb2gqxi2ytfcH-J9NonA3yVopiIohj0oXzWnm5UnO4_Q"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/vnd.allegro.public.v1+json",
    "Accept": "application/vnd.allegro.public.v1+json",
}


def get_order_events():
    url = base_url + "order/events"

    # types = ["BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING", "BUYER_CANCELLED",
    # "FULFILLMENT_STATUS_CHANGED", "AUTO_CANCELLED"]

    types = ["BUYER_CANCELLED"]

    response = requests.get(headers=headers, url=url, params={"type": types, "limit": 10})
    # print(json.dumps(response.json(), indent=2))
    with open("file1.json", "w") as f:
        f.write(json.dumps(response.json(), indent=2))


def an_order_details(id_):
    url = base_url + f"order/checkout-forms/{id_}"
    response = requests.get(url=url, headers=headers)
    with open("details.json", "w") as f:
        f.write(json.dumps(response.json(), indent=2, ensure_ascii=False))

def get_order_list():
    url = base_url + "order/checkout-forms"
    response = requests.get(headers=headers, url=url, params={'limit': 100})

    with open("list.json", "w") as f:
        f.write(json.dumps(response.json(), indent=2, ensure_ascii=False))

    li = [(item["id"], item["status"], item["fulfillment"]["status"]) for item in response.json()["checkoutForms"]]

    for item in response.json()["checkoutForms"]:
        if len(item['lineItems']) > 1:
            print(item)
        # print(f"{item['id']}: status: {item['status']} Fulfillment status: {item['fulfillment']['status']}")

    # print(len(li))
    # print(len(set(li)))

# get_order_events()
# an_order_details("4d576d60-f759-11ef-a8d3-1154fd9153a6")

get_order_list()
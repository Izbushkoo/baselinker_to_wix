from fastapi import APIRouter

from app.api.v1.routers import auth, users, baselinker_info, allegro_tokens, allegro_sync, warehouse, products, operations, allegro_orders, prices, stock_sync, allegro_webhooks, catalog, offer_transfer

# API маршруты
api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(allegro_tokens.router, prefix="/allegro_tokens", tags=["Allegro tokens"])
api_router.include_router(baselinker_info.router, prefix="/baselinker", tags=["Baselinker"])
api_router.include_router(allegro_sync.router, prefix="/allegro_sync", tags=["Allegro sync"])
api_router.include_router(warehouse.router, prefix="/warehouse", tags=["Warehouse"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(prices.router, prefix="/prices", tags=["Prices"])
api_router.include_router(stock_sync.router, prefix="/stock-sync", tags=["Stock Sync"])
api_router.include_router(allegro_webhooks.router, prefix="/allegro", tags=["Allegro Webhooks"])
# Убираем дублирование - offer_transfer только в web_router для фронтенда

# Веб-маршруты (без API префикса)
web_router = APIRouter()
web_router.include_router(auth.web_router, tags=["Auth Pages"])
web_router.include_router(catalog.router, prefix="/catalog_new", tags=["New Catalog Pages"])
web_router.include_router(products.catalog_router, prefix="/catalog_new/api", tags=["Catalog API"])
web_router.include_router(products.web_router, prefix="/products", tags=["Product Pages"])
web_router.include_router(operations.web_router)
web_router.include_router(allegro_sync.web_router)
web_router.include_router(allegro_tokens.web_router, tags=["Allegro tokens"])
web_router.include_router(allegro_orders.web_router, tags=["Allegro orders"])
web_router.include_router(stock_sync.web_router, tags=["Stock Sync Pages"])
web_router.include_router(offer_transfer.router, prefix="/offer-transfer", tags=["Offer Transfer Frontend"])  # Фронтенд система переноса офферов
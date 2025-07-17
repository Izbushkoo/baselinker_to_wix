from fastapi import APIRouter

from app.api.v1.routers import auth, users, baselinker_info, allegro_tokens, allegro_sync, warehouse, products, operations, allegro_orders, prices

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
# Веб-маршруты (без API префикса)
web_router = APIRouter()
web_router.include_router(auth.web_router, tags=["Auth Pages"])
web_router.include_router(products.catalog_router, tags=["Catalog Pages"])
web_router.include_router(products.web_router, prefix="/products", tags=["Product Pages"])
web_router.include_router(operations.web_router)
web_router.include_router(allegro_sync.web_router)
web_router.include_router(allegro_tokens.web_router, tags=["Allegro tokens"])
web_router.include_router(allegro_orders.web_router, tags=["Allegro orders"])
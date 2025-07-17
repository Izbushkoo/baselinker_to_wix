"""
Automatically add all models to __all__
This is used in alembic while autogenerate database migration script.
"""
import glob
from os.path import basename, dirname, isfile, join

# Импорт всех моделей для SQLModel
from .warehouse import Product, Stock, Sale, Transfer
from .user import User
from .allegro_token import AllegroToken
from .allegro_order import AllegroOrder, AllegroBuyer, AllegroLineItem, OrderLineItem
from .allegro_event_tracker import AllegroEventTracker
from .operations import Operation
from .product_sync_lock import ProductSyncLock
from .product_allegro_sync_settings import ProductAllegroSyncSettings

modules = glob.glob(join(dirname(__file__), "*.py"))
__all__ = [basename(f)[:-3] for f in modules if isfile(f) and not f.endswith("__init__.py")]

__all__ = [
    "Product",
    "Stock", 
    "Sale",
    "Transfer",
    "User",
    "AllegroToken",
    "AllegroOrder",
    "AllegroBuyer",
    "AllegroLineItem",
    "OrderLineItem",
    "AllegroEventTracker",
    "Operation",
    "ProductSyncLock",
    "ProductAllegroSyncSettings",
]

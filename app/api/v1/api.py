from fastapi import APIRouter

from app.api.v1.routers import auth, users, baselinker_info, allegro_tokens

api_router = APIRouter()
# api_router.include_router(users.router, prefix="/users", tags=["Rsers"])
# api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(allegro_tokens.router, prefix="/allegro_tokens", tags=["Allegro tokens"])
api_router.include_router(baselinker_info.router, prefix="/baselinker", tags=["Baselinker"])

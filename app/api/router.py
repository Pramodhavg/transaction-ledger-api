from fastapi import APIRouter

from app.api.routes import accounts, health, transactions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)

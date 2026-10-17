from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator
from app.schemas.api import ErrorResponse, ProductCreated
from app.schemas.label import VerificationSubmission
from app.store import Store, get_store

router = APIRouter(tags=["保健食品"])


@router.post(
    "/api/products",
    response_model=ProductCreated,
    status_code=201,
    summary="送出核對完成的保健食品",
    description=(
        "PG-007 保健食品人工校對頁全部鎖定、按「下一步」時呼叫。後端重算攝取量與營養素量"
        "（前端送來的計算欄位一律不採信），存成一罐已核對的產品，回傳 product_id 供送出評估時使用。"
    ),
    responses={422: {"model": ErrorResponse, "description": "送出的欄位不完整或格式不對"}},
)
def create_product(
    submission: VerificationSubmission,
    calculator: Calculator = Depends(get_calculator),
    store: Store = Depends(get_store),
) -> ProductCreated:
    """W3：送出時帶草稿的 product_id，後端比對草稿產生修正紀錄。"""
    product = calculator.verify_product(uuid4(), submission, datetime.now(UTC))
    store.save_product(product)
    return ProductCreated(product_id=product.product_id)

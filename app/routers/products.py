from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator
from app.schemas.api import ProductCreated
from app.schemas.label import VerificationSubmission
from app.store import Store, get_store

router = APIRouter()


@router.post("/api/products", response_model=ProductCreated, status_code=201)
def create_product(
    submission: VerificationSubmission,
    calculator: Calculator = Depends(get_calculator),
    store: Store = Depends(get_store),
) -> ProductCreated:
    product = calculator.verify_product(uuid4(), submission, datetime.now(UTC))
    store.save_product(product)
    return ProductCreated(product_id=product.product_id)

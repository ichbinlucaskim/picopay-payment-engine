from pydantic import BaseModel, Field
from typing import Optional
import uuid
from app.models import TransactionStatus


class ChargeRequest(BaseModel):
    user_id: int = Field(..., description="ID of the user making the charge")
    amount: float = Field(..., gt=0, description="Amount to charge (must be positive)")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code (3 characters)")


class TransactionResponse(BaseModel):
    id: int
    user_id: int
    amount: float
    currency: str
    status: TransactionStatus
    idempotency_key: Optional[uuid.UUID] = None

    class Config:
        from_attributes = True


class ChargeResponse(BaseModel):
    message: str
    transaction: TransactionResponse
    new_balance: float


class ErrorResponse(BaseModel):
    detail: str


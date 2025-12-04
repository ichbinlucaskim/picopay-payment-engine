from fastapi import FastAPI, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import uuid
import logging
import time
from app.database import get_db, engine, Base
from app.models import User, Transaction, TransactionStatus
from app.schemas import ChargeRequest, ChargeResponse, ErrorResponse, TransactionResponse
from app.cache import get_cached_transaction, cache_transaction
from app.auth import verify_api_key
from app.metrics import record_charge_request, get_metrics
from prometheus_client import CONTENT_TYPE_LATEST

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PicoPay Payment Engine", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    """Create database tables on startup"""
    Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {"message": "Welcome to PicoPay Payment Engine"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    """
    Expose Prometheus metrics endpoint.
    
    Returns:
        Response: Prometheus metrics in text format
    """
    return Response(content=get_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/charge", response_model=ChargeResponse, status_code=status.HTTP_200_OK)
async def charge(
    charge_request: ChargeRequest,
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Process a charge transaction atomically.
    Deducts the amount from user's balance and creates a transaction record.
    If balance is insufficient, returns 400 Bad Request and rolls back the transaction.
    
    Requires API key authentication via X-API-Key header.
    
    Supports idempotency via Idempotency-Key header. If a request with the same
    Idempotency-Key already exists and has COMPLETED status, returns the previous result.
    
    Uses Redis cache for fast idempotency lookups before querying PostgreSQL.
    """
    # Start timing for metrics
    start_time = time.time()
    
    # Extract Idempotency-Key from header if present
    idempotency_key_str = request.headers.get("Idempotency-Key")
    idempotency_key = None
    if idempotency_key_str:
        try:
            idempotency_key = uuid.UUID(idempotency_key_str)
        except ValueError:
            duration = time.time() - start_time
            record_charge_request('failed', duration)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Idempotency-Key format. Must be a valid UUID."
            )
    
    # Check Redis cache first for idempotency key
    if idempotency_key:
        cached_result = get_cached_transaction(str(idempotency_key))
        if cached_result:
            # Cache hit - return cached response immediately without touching database
            # Reconstruct the response from cached data
            transaction_data = cached_result.get('transaction', {})
            logger.info(
                f"Cache hit: Idempotency-Key={idempotency_key}, "
                f"Returned Transaction ID={transaction_data.get('id')}"
            )
            
            # Convert status string back to enum
            status_enum = TransactionStatus(transaction_data.get('status'))
            # Convert idempotency_key string back to UUID if present
            cached_idempotency_key = None
            if transaction_data.get('idempotency_key'):
                cached_idempotency_key = uuid.UUID(transaction_data.get('idempotency_key'))
            
            # Record metrics for idempotent hit
            duration = time.time() - start_time
            record_charge_request('idempotent_hit', duration)
            
            return ChargeResponse(
                message=cached_result.get('message', 'Charge processed successfully (idempotent)'),
                transaction=TransactionResponse(
                    id=transaction_data.get('id'),
                    user_id=transaction_data.get('user_id'),
                    amount=transaction_data.get('amount'),
                    currency=transaction_data.get('currency'),
                    status=status_enum,
                    idempotency_key=cached_idempotency_key
                ),
                new_balance=cached_result.get('new_balance', 0.0)
            )
    
    # Cache miss or no idempotency key - proceed with database transaction
    # Start a database transaction
    try:
        # Check for existing transaction with the same idempotency_key within the transaction
        # This ensures concurrency safety - we lock the row if it exists
        if idempotency_key:
            existing_transaction = (
                db.query(Transaction)
                .filter(Transaction.idempotency_key == idempotency_key)
                .with_for_update()
                .first()
            )
            
            # If a completed transaction exists, return it immediately
            if existing_transaction and existing_transaction.status == TransactionStatus.COMPLETED:
                # Get the user's current balance (which should match the balance after this transaction)
                user = db.query(User).filter(User.id == existing_transaction.user_id).first()
                
                # Log idempotency hit
                logger.info(
                    f"Idempotency hit: Idempotency-Key={idempotency_key}, "
                    f"Returned Transaction ID={existing_transaction.id}"
                )
                
                # Build response
                response = ChargeResponse(
                    message="Charge processed successfully (idempotent)",
                    transaction=TransactionResponse(
                        id=existing_transaction.id,
                        user_id=existing_transaction.user_id,
                        amount=existing_transaction.amount,
                        currency=existing_transaction.currency,
                        status=existing_transaction.status,
                        idempotency_key=existing_transaction.idempotency_key
                    ),
                    new_balance=user.balance if user else 0.0
                )
                
                # Cache the result for future requests
                cache_data = {
                    "message": response.message,
                    "transaction": {
                        "id": response.transaction.id,
                        "user_id": response.transaction.user_id,
                        "amount": response.transaction.amount,
                        "currency": response.transaction.currency,
                        "status": response.transaction.status.value,
                        "idempotency_key": str(response.transaction.idempotency_key) if response.transaction.idempotency_key else None
                    },
                    "new_balance": response.new_balance
                }
                cache_transaction(str(idempotency_key), cache_data)
                
                return response
        
        # Lock the user row for update to prevent race conditions
        user = db.query(User).filter(User.id == charge_request.user_id).with_for_update().first()
        
        if not user:
            duration = time.time() - start_time
            record_charge_request('failed', duration)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {charge_request.user_id} not found"
            )
        
        # Check if balance is sufficient
        if user.balance < charge_request.amount:
            # Log insufficient balance failure
            logger.info(
                f"Insufficient balance failure: User ID={charge_request.user_id}, "
                f"Requested Amount={charge_request.amount}"
            )
            # Rollback the transaction explicitly
            db.rollback()
            # Record metrics for insufficient balance
            duration = time.time() - start_time
            record_charge_request('insufficient_balance', duration)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient balance. Current balance: {user.balance}, Required: {charge_request.amount}"
            )
        
        # Deduct the amount from user's balance
        user.balance -= charge_request.amount
        
        # Create transaction record
        transaction = Transaction(
            user_id=charge_request.user_id,
            amount=charge_request.amount,
            currency=charge_request.currency,
            status=TransactionStatus.COMPLETED,
            idempotency_key=idempotency_key
        )
        db.add(transaction)
        
        # Commit the transaction atomically
        db.commit()
        
        # Refresh to get the latest data
        db.refresh(transaction)
        db.refresh(user)
        
        # Log successful new charge
        logger.info(
            f"Successful new charge: Transaction ID={transaction.id}, "
            f"User ID={transaction.user_id}"
        )
        
        # Build response
        response = ChargeResponse(
            message="Charge processed successfully",
            transaction=TransactionResponse(
                id=transaction.id,
                user_id=transaction.user_id,
                amount=transaction.amount,
                currency=transaction.currency,
                status=transaction.status,
                idempotency_key=transaction.idempotency_key
            ),
            new_balance=user.balance
        )
        
        # Cache the successful transaction result in Redis
        if idempotency_key:
            cache_data = {
                "message": response.message,
                "transaction": {
                    "id": response.transaction.id,
                    "user_id": response.transaction.user_id,
                    "amount": response.transaction.amount,
                    "currency": response.transaction.currency,
                    "status": response.transaction.status.value,
                    "idempotency_key": str(response.transaction.idempotency_key) if response.transaction.idempotency_key else None
                },
                "new_balance": response.new_balance
            }
            cache_transaction(str(idempotency_key), cache_data)
        
        # Record metrics for successful charge
        duration = time.time() - start_time
        record_charge_request('success', duration)
        
        return response
        
    except HTTPException as e:
        # Record metrics for failed requests (HTTP exceptions)
        duration = time.time() - start_time
        # Determine status based on HTTP status code
        if e.status_code == status.HTTP_400_BAD_REQUEST:
            # Could be insufficient balance or invalid request
            # Check if we already recorded it (insufficient_balance is recorded above)
            # If we get here from another 400, it's a different failure
            if 'insufficient' not in str(e.detail).lower():
                record_charge_request('failed', duration)
        else:
            record_charge_request('failed', duration)
        # Re-raise HTTP exceptions (they already have rollback)
        raise
    except IntegrityError as e:
        # Handle unique constraint violation (duplicate idempotency_key)
        db.rollback()
        if idempotency_key:
            # If we get here, another request with the same key was processed concurrently
            # Query again to get the completed transaction
            existing_transaction = (
                db.query(Transaction)
                .filter(Transaction.idempotency_key == idempotency_key)
                .first()
            )
            if existing_transaction and existing_transaction.status == TransactionStatus.COMPLETED:
                user = db.query(User).filter(User.id == existing_transaction.user_id).first()
                
                # Log idempotency hit (from IntegrityError path)
                logger.info(
                    f"Idempotency hit: Idempotency-Key={idempotency_key}, "
                    f"Returned Transaction ID={existing_transaction.id}"
                )
                
                # Build response
                response = ChargeResponse(
                    message="Charge processed successfully (idempotent)",
                    transaction=TransactionResponse(
                        id=existing_transaction.id,
                        user_id=existing_transaction.user_id,
                        amount=existing_transaction.amount,
                        currency=existing_transaction.currency,
                        status=existing_transaction.status,
                        idempotency_key=existing_transaction.idempotency_key
                    ),
                    new_balance=user.balance if user else 0.0
                )
                
                # Cache the result for future requests
                cache_data = {
                    "message": response.message,
                    "transaction": {
                        "id": response.transaction.id,
                        "user_id": response.transaction.user_id,
                        "amount": response.transaction.amount,
                        "currency": response.transaction.currency,
                        "status": response.transaction.status.value,
                        "idempotency_key": str(response.transaction.idempotency_key) if response.transaction.idempotency_key else None
                    },
                    "new_balance": response.new_balance
                }
                cache_transaction(str(idempotency_key), cache_data)
                
                # Record metrics for idempotent hit (from IntegrityError path)
                duration = time.time() - start_time
                record_charge_request('idempotent_hit', duration)
                
                return response
        
        # If we get here, it's a database integrity error that we can't handle
        duration = time.time() - start_time
        record_charge_request('failed', duration)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database integrity error: {str(e)}"
        )
    except Exception as e:
        # Rollback on any other error
        db.rollback()
        # Record metrics for failed requests
        duration = time.time() - start_time
        record_charge_request('failed', duration)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the charge: {str(e)}"
        )


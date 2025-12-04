#!/usr/bin/env python3
"""
Concurrency test script for idempotency verification.
Sends 10 concurrent POST /charge requests with the same Idempotency-Key
and verifies that only one transaction is created and balance is deducted only once.
"""

import requests
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import time
import os

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/picopay")

# Test parameters
USER_ID = 1
AMOUNT = 100.0
CURRENCY = "USD"
IDEMPOTENCY_KEY = str(uuid.uuid4())
NUM_CONCURRENT_REQUESTS = 10


def send_charge_request(request_num: int) -> dict:
    """Send a POST /charge request with idempotency key."""
    url = f"{API_BASE_URL}/charge"
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": IDEMPOTENCY_KEY
    }
    payload = {
        "user_id": USER_ID,
        "amount": AMOUNT,
        "currency": CURRENCY
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        return {
            "request_num": request_num,
            "status_code": response.status_code,
            "response": response.json(),
            "success": response.status_code == 200
        }
    except Exception as e:
        return {
            "request_num": request_num,
            "status_code": None,
            "error": str(e),
            "success": False
        }


def get_user_balance_and_transaction_count(db_session, user_id: int, idempotency_key: str):
    """Query database to get user balance and transaction count for the idempotency key."""
    # Get user balance
    user_query = text("SELECT balance FROM users WHERE id = :user_id")
    user_result = db_session.execute(user_query, {"user_id": user_id}).fetchone()
    balance = user_result[0] if user_result else None
    
    # Count transactions with the idempotency key
    transaction_query = text("""
        SELECT COUNT(*) 
        FROM transactions 
        WHERE idempotency_key = CAST(:idempotency_key AS uuid)
    """)
    transaction_result = db_session.execute(
        transaction_query, 
        {"idempotency_key": idempotency_key}
    ).fetchone()
    transaction_count = transaction_result[0] if transaction_result else 0
    
    # Get transaction details for verification
    details_query = text("""
        SELECT id, user_id, amount, currency, status 
        FROM transactions 
        WHERE idempotency_key = CAST(:idempotency_key AS uuid)
    """)
    transaction_details = db_session.execute(
        details_query,
        {"idempotency_key": idempotency_key}
    ).fetchall()
    
    return balance, transaction_count, transaction_details


def main():
    print("=" * 80)
    print("IDEMPOTENCY CONCURRENCY TEST")
    print("=" * 80)
    print(f"\nTest Configuration:")
    print(f"  API URL: {API_BASE_URL}")
    print(f"  User ID: {USER_ID}")
    print(f"  Amount: {AMOUNT} {CURRENCY}")
    print(f"  Idempotency Key: {IDEMPOTENCY_KEY}")
    print(f"  Concurrent Requests: {NUM_CONCURRENT_REQUESTS}")
    print()
    
    # Get initial balance
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db_session = SessionLocal()
    
    try:
        initial_query = text("SELECT balance FROM users WHERE id = :user_id")
        initial_result = db_session.execute(initial_query, {"user_id": USER_ID}).fetchone()
        
        if not initial_result:
            print(f"ERROR: User with id {USER_ID} does not exist in the database.")
            print("Please create a user first or update USER_ID in the script.")
            return
        
        initial_balance = initial_result[0]
        print(f"Initial User Balance: {initial_balance} {CURRENCY}")
        print()
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        print(f"Database URL: {DATABASE_URL}")
        print("\nMake sure the database is running and accessible.")
        return
    finally:
        db_session.close()
    
    # Send concurrent requests
    print(f"Sending {NUM_CONCURRENT_REQUESTS} concurrent requests...")
    print("-" * 80)
    
    start_time = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_REQUESTS) as executor:
        # Submit all requests
        futures = {
            executor.submit(send_charge_request, i+1): i+1 
            for i in range(NUM_CONCURRENT_REQUESTS)
        }
        
        # Collect results as they complete
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "✓" if result["success"] else "✗"
            print(f"Request {result['request_num']:2d}: {status} "
                  f"(Status: {result.get('status_code', 'ERROR')})")
    
    elapsed_time = time.time() - start_time
    print("-" * 80)
    print(f"All requests completed in {elapsed_time:.2f} seconds")
    print()
    
    # Wait a moment for any final database commits
    time.sleep(0.5)
    
    # Query database for final state
    print("Querying database for verification...")
    print("-" * 80)
    
    db_session = SessionLocal()
    try:
        final_balance, transaction_count, transaction_details = get_user_balance_and_transaction_count(
            db_session, USER_ID, IDEMPOTENCY_KEY
        )
        
        # Calculate expected balance
        expected_balance = initial_balance - AMOUNT
        
        # Print results
        print(f"\nRESULTS:")
        print(f"  Initial Balance:     {initial_balance:.2f} {CURRENCY}")
        print(f"  Final Balance:       {final_balance:.2f} {CURRENCY}")
        print(f"  Expected Balance:    {expected_balance:.2f} {CURRENCY}")
        print(f"  Amount Deducted:     {initial_balance - final_balance:.2f} {CURRENCY}")
        print(f"  Transaction Count:   {transaction_count}")
        print()
        
        # Verification
        print("=" * 80)
        print("VERIFICATION:")
        print("=" * 80)
        
        balance_correct = abs(final_balance - expected_balance) < 0.01
        transaction_count_correct = transaction_count == 1
        
        if balance_correct:
            print("✓ Balance deduction: CORRECT (deducted exactly once)")
        else:
            print(f"✗ Balance deduction: INCORRECT")
            print(f"  Expected: {expected_balance:.2f}, Got: {final_balance:.2f}")
        
        if transaction_count_correct:
            print("✓ Transaction count: CORRECT (exactly 1 transaction created)")
        else:
            print(f"✗ Transaction count: INCORRECT")
            print(f"  Expected: 1, Got: {transaction_count}")
        
        if transaction_details:
            print(f"\nTransaction Details:")
            for tx in transaction_details:
                print(f"  ID: {tx[0]}, User ID: {tx[1]}, Amount: {tx[2]} {tx[3]}, Status: {tx[4]}")
        
        print()
        if balance_correct and transaction_count_correct:
            print("🎉 IDEMPOTENCY TEST PASSED!")
            print("   The system correctly handled concurrent requests with the same Idempotency-Key.")
            print("   Balance was deducted only once and only one transaction was created.")
        else:
            print("❌ IDEMPOTENCY TEST FAILED!")
            print("   The system did not properly handle idempotency.")
        
        print("=" * 80)
        
        # Print request results summary
        successful_requests = sum(1 for r in results if r["success"])
        print(f"\nRequest Summary:")
        print(f"  Successful: {successful_requests}/{NUM_CONCURRENT_REQUESTS}")
        print(f"  Failed: {NUM_CONCURRENT_REQUESTS - successful_requests}/{NUM_CONCURRENT_REQUESTS}")
        
    except Exception as e:
        print(f"ERROR: Could not query database: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db_session.close()
        engine.dispose()


if __name__ == "__main__":
    main()


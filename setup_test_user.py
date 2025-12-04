#!/usr/bin/env python3
"""
Helper script to create a test user with an initial balance for testing.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import sys

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/picopay")
USER_ID = 1
INITIAL_BALANCE = 1000.0


def setup_test_user():
    """Create or update a test user with initial balance."""
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db_session = SessionLocal()
    
    try:
        # Check if user exists
        check_query = text("SELECT id, balance FROM users WHERE id = :user_id")
        result = db_session.execute(check_query, {"user_id": USER_ID}).fetchone()
        
        if result:
            # Update existing user
            update_query = text("UPDATE users SET balance = :balance WHERE id = :user_id")
            db_session.execute(update_query, {"balance": INITIAL_BALANCE, "user_id": USER_ID})
            db_session.commit()
            print(f"✓ Updated user {USER_ID} with balance: {INITIAL_BALANCE}")
        else:
            # Create new user
            insert_query = text("INSERT INTO users (id, balance) VALUES (:user_id, :balance)")
            db_session.execute(insert_query, {"user_id": USER_ID, "balance": INITIAL_BALANCE})
            db_session.commit()
            print(f"✓ Created user {USER_ID} with balance: {INITIAL_BALANCE}")
        
        # Verify
        verify_query = text("SELECT id, balance FROM users WHERE id = :user_id")
        verify_result = db_session.execute(verify_query, {"user_id": USER_ID}).fetchone()
        print(f"✓ Verified: User {verify_result[0]} has balance {verify_result[1]}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        db_session.rollback()
        sys.exit(1)
    finally:
        db_session.close()
        engine.dispose()


if __name__ == "__main__":
    print("Setting up test user...")
    setup_test_user()
    print("Done!")


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from typing import Generator
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/picopay")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database session management.
    
    Yields a database session and ensures proper cleanup after the request.
    This follows FastAPI's dependency injection best practices using yield.
    
    Yields:
        Session: SQLAlchemy database session
        
    Example:
        @app.post("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            # Use db here
            pass
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


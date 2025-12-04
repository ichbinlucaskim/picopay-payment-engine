# PicoPay Payment Engine

**A Robust, Idempotent Payment Gateway Backend with ACID Guarantees**

---

## The Challenge Solved

Payment processing systems face critical engineering challenges that must be solved to ensure financial correctness and system reliability:

- **Double-Spending Prevention**: Ensuring that duplicate requests do not result in multiple charges, even under high concurrency conditions
- **ACID Transaction Guarantees**: Maintaining data consistency when deducting user balances and creating transaction records as a single atomic operation
- **High Concurrency Handling**: Processing multiple simultaneous requests safely without race conditions or data corruption
- **Performance at Scale**: Optimizing response times for duplicate request detection while maintaining correctness guarantees

This system addresses these challenges through a carefully architected solution combining PostgreSQL's ACID transaction model, Redis caching for performance optimization, and comprehensive observability instrumentation.

---

## Core Architecture Overview

The PicoPay Payment Engine is built on a modern, production-ready technology stack:

**Application Layer:**
- **FastAPI** (Python 3.11): High-performance asynchronous web framework for RESTful API implementation
- **Uvicorn**: ASGI server for production deployment with worker process support
- **SQLAlchemy 2.0**: Modern ORM with type-safe models and declarative syntax

**Data Layer:**
- **PostgreSQL 15**: Relational database providing ACID transaction guarantees, row-level locking, and referential integrity
- **Redis 7**: In-memory data store for high-performance idempotency key caching with TTL-based expiration

**Observability:**
- **Prometheus**: Metrics collection and export for monitoring, alerting, and performance analysis
- **Structured Logging**: Application-level logging with appropriate log levels for operational visibility

**Infrastructure:**
- **Docker**: Containerization with multi-stage builds for optimized image size and security
- **Docker Compose**: Local development environment orchestration

---

## Killer Features (Engineering Focus)

### Data Integrity: Atomicity via PostgreSQL Transactions

The system ensures financial correctness through PostgreSQL's ACID transaction model. Balance deductions and transaction record creation are executed within a single database transaction, providing all-or-nothing semantics. Row-level locking via `SELECT ... FOR UPDATE` prevents race conditions when multiple concurrent requests target the same user account.

**Technical Implementation:**
- Single transaction boundary for balance deduction and transaction creation
- Explicit rollback on validation failures (insufficient balance, user not found)
- Isolation level prevents dirty reads and lost updates
- Durability guarantees ensure committed transactions survive system failures

### Scalability & Idempotency: Low-Latency Duplicate Request Prevention

A two-layer idempotency mechanism combines Redis caching for performance with PostgreSQL for consistency guarantees. The Redis cache provides sub-millisecond lookups for duplicate request detection, while the database layer ensures correctness even if the cache is unavailable.

**Technical Implementation:**
- **Layer 1 (Redis)**: Fast-path cache lookup using `idempotency:{uuid}` key format with 24-hour TTL
- **Layer 2 (PostgreSQL)**: Safe-path database transaction with row-level locking for authoritative idempotency checking
- Graceful degradation: System falls back to database if Redis is unavailable
- Cache write strategy: Successful transactions are cached after commit to optimize future duplicate requests

**Performance Characteristics:**
- Cache hit latency: < 1 millisecond
- Database query latency: 10-50 milliseconds
- Estimated 70-80% reduction in database load for duplicate requests

### Observability: Prometheus Metrics Instrumentation

Comprehensive metrics collection enables monitoring of system health, performance, and business metrics. The system tracks request volume, latency distribution, and outcome classification to support operational decision-making.

**Metrics Implemented:**
- **Counter**: `charge_requests_total` with status labels (success, idempotent_hit, insufficient_balance, failed)
- **Histogram**: `charge_request_latency_seconds` with configurable buckets for percentile analysis
- **Export Endpoint**: `/metrics` endpoint exposing Prometheus text format for standard monitoring system integration

**Use Cases:**
- Request rate monitoring and alerting
- Success rate calculation and SLA compliance
- Latency percentile analysis (p50, p95, p99)
- Idempotency effectiveness measurement (cache hit rates)

### Security: API Key Authentication

The system implements API key-based authentication to restrict access to authorized clients. Authentication is enforced via FastAPI dependency injection, ensuring all charge requests are validated before business logic execution.

**Security Features:**
- Header-based authentication via `X-API-Key` header
- Environment variable storage for API key secrets (not in code or version control)
- HTTP 401 Unauthorized responses for missing or invalid keys
- Security audit logging with partial key masking

**Production Recommendations:**
- Integration with secrets management services (AWS Secrets Manager, HashiCorp Vault)
- API key rotation policies
- Rate limiting per API key
- HTTPS/TLS enforcement for all API traffic

---

## Getting Started

### Prerequisites

- Docker and Docker Compose installed
- Git for cloning the repository

### Development Environment Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd picopay-payment-engine
   ```

2. **Start the development environment:**
   ```bash
   docker compose up --build
   ```

   This command will:
   - Build the FastAPI application container
   - Start PostgreSQL database (port 5433)
   - Start Redis cache (port 6379)
   - Start the FastAPI application (port 8000)

3. **Verify services are running:**
   ```bash
   curl http://localhost:8000/health
   # Expected: {"status":"healthy"}
   ```

4. **Set up test user (optional):**
   ```bash
   python3 setup_test_user.py
   ```

5. **Run idempotency concurrency test:**
   ```bash
   python3 test_idempotency.py
   ```

### Environment Variables

Configure the following environment variables for production deployment:

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_HOST`: Redis server hostname (default: redis)
- `REDIS_PORT`: Redis server port (default: 6379)
- `APP_API_KEY`: API key for authentication
- `CACHE_TTL`: Cache time-to-live in seconds (default: 86400)

### API Usage Example

**Authenticated Charge Request:**
```bash
curl -X POST "http://localhost:8000/charge" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-api-key-change-in-production" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{
    "user_id": 1,
    "amount": 50.0,
    "currency": "USD"
  }'
```

**Metrics Endpoint:**
```bash
curl http://localhost:8000/metrics
```

---

## Documentation

For comprehensive technical documentation, refer to:

- **[DEPLOY.md](doc/DEPLOY.md)**: Detailed deployment guide covering cloud deployment options, database setup, security considerations, CI/CD pipeline configuration, and troubleshooting
- **[REPORT.md](doc/REPORT.md)**: Complete technical architecture analysis including system diagrams, implementation details for atomicity and idempotency, observability and security rationale, and empirical verification results from concurrency testing

---

## Project Structure

```
picopay-payment-engine/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application and endpoints
│   ├── models.py            # SQLAlchemy 2.0 data models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── database.py          # Database connection and session management
│   ├── cache.py             # Redis caching layer implementation
│   ├── auth.py              # API key authentication
│   └── metrics.py           # Prometheus metrics instrumentation
├── doc/
│   ├── DEPLOY.md            # Deployment documentation
│   ├── REPORT.md            # Technical architecture report
│   ├── DESIGN_GUIDE.md      # Senior-level design and study guide
│   └── prompt.md            # Prompt input log and specification
├── docker-compose.yml       # Development environment configuration
├── docker-compose.prod.yml  # Production environment configuration
├── Dockerfile               # Multi-stage container build
├── requirements.txt         # Python dependencies
├── test_idempotency.py      # Concurrency and idempotency test suite
├── setup_test_user.py       # Test data initialization script
└── README.md                # This file
```

---

## Key Endpoints

- `POST /charge`: Process payment charge with idempotency support
- `GET /metrics`: Prometheus metrics export endpoint
- `GET /health`: Application health check endpoint

---

## Engineering Achievements

This project demonstrates expertise in:

- **Distributed Systems**: Designing systems that maintain consistency across multiple data stores (PostgreSQL and Redis)
- **Concurrency Control**: Implementing safe concurrent operations using database row-level locking and transaction isolation
- **Performance Optimization**: Balancing correctness guarantees with performance requirements through strategic caching
- **Observability Engineering**: Instrumenting applications with comprehensive metrics for production monitoring
- **Security Engineering**: Implementing authentication mechanisms following security best practices
- **Containerization**: Optimizing Docker images through multi-stage builds and security hardening

---

## License

This project is provided as a technical demonstration and portfolio piece.

---

**Version**: 1.0.0  
**Last Updated**: December 2025

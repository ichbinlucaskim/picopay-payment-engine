# PicoPay Payment Engine - Senior-Level Technical Study Guide

**Principal Engineer Technical Mentorship Document**

This guide is designed to elevate understanding from implementation-level to senior engineering architecture and design principles. Each section rigorously addresses the "Why" and "How" behind critical technical decisions.

---

## Table of Contents

1. [Core Concepts Deep Dive (CS & Finance)](#1-core-concepts-deep-dive-cs--finance)
2. [Architecture Rationale (Architecture Decisions)](#2-architecture-rationale-architecture-decisions)
3. [Code Implementation Analysis (Line-by-Line Logic)](#3-code-implementation-analysis-line-by-line-logic)
4. [Infrastructure & Observability (DevOps View)](#4-infrastructure--observability-devops-view)
5. [Design Trade-offs & Scalability (The Senior Interview)](#5-design-trade-offs--scalability-the-senior-interview)

---

## 1. Core Concepts Deep Dive (CS & Finance)

### 1.1 Idempotency (멱등성): Why is it Crucial in Payment Systems?

#### The Problem: Financial Double-Spending

In payment systems, idempotency is not merely a best practice—it is a **financial correctness requirement**. Consider the following scenario:

**Without Idempotency:**
```
Request 1: POST /charge {user_id: 1, amount: 100, idempotency_key: "abc"}
Request 2: POST /charge {user_id: 1, amount: 100, idempotency_key: "abc"}  # Network retry

Result: User charged $200 instead of $100
Financial Impact: Customer overcharged, regulatory violation, potential legal liability
```

**With Idempotency:**
```
Request 1: POST /charge {user_id: 1, amount: 100, idempotency_key: "abc"}
Request 2: POST /charge {user_id: 1, amount: 100, idempotency_key: "abc"}  # Network retry

Result: User charged $100, second request returns same transaction ID
Financial Impact: Correct behavior, customer satisfaction, regulatory compliance
```

#### HTTP Method Semantics: Safe vs. Idempotent vs. Non-Idempotent

**Safe Methods (GET, HEAD, OPTIONS):**
- **Definition**: Methods that do not modify server state
- **Property**: Safe methods are inherently idempotent (calling them multiple times has no side effects)
- **Use Case**: Read operations, health checks

**Idempotent Methods (PUT, DELETE, PATCH with idempotency semantics):**
- **Definition**: Methods where multiple identical requests produce the same result as a single request
- **Mathematical Property**: f(f(x)) = f(x)
- **Example**: `PUT /users/1 {balance: 1000}` called 10 times results in balance = 1000 (not 10000)
- **Use Case**: Update operations where the final state is deterministic

**Non-Idempotent Methods (POST):**
- **Definition**: Methods where each request may produce different results
- **Problem**: `POST /charge` called twice with same parameters creates two separate charges
- **Solution**: Explicit idempotency key mechanism required
- **Implementation**: Client provides unique `Idempotency-Key` header, server ensures same key = same result

#### Why POST Requires Explicit Idempotency

POST is designed for **resource creation**, where each request conceptually creates a new resource. In payment systems, we need to **prevent** this default behavior:

```python
# Without idempotency (default POST behavior)
POST /charge → Transaction ID: 1
POST /charge → Transaction ID: 2  # Different resource created

# With idempotency key
POST /charge + Idempotency-Key: "abc" → Transaction ID: 1
POST /charge + Idempotency-Key: "abc" → Transaction ID: 1  # Same resource returned
```

**Key Insight**: The idempotency key transforms a non-idempotent POST into an idempotent operation by making the request identity deterministic.

### 1.2 ACID Properties: Atomicity and Isolation Deep Dive

#### Atomicity: "All or Nothing"

**Definition**: A transaction is an indivisible unit of work. Either all operations within the transaction succeed, or all operations are rolled back.

**Implementation in PicoPay:**

```python
# Atomic transaction boundary
try:
    # Operation 1: Lock user row
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    
    # Operation 2: Validate balance
    if user.balance < amount:
        db.rollback()  # Atomic rollback - no partial state
        raise InsufficientBalanceError()
    
    # Operation 3: Deduct balance
    user.balance -= amount
    
    # Operation 4: Create transaction record
    transaction = Transaction(...)
    db.add(transaction)
    
    # Atomic commit - all operations succeed together
    db.commit()
    
except Exception:
    db.rollback()  # Atomic rollback on any error
    raise
```

**Why Atomicity Matters in Payments:**

Consider what happens **without** atomicity:
```
Step 1: user.balance -= 100  # Committed
Step 2: Create transaction record  # Failed (database error)

Result: Balance deducted but no transaction record
Problem: Financial ledger inconsistency, audit trail broken
```

With atomicity, both operations succeed or both fail—no partial state possible.

#### Isolation: Preventing Concurrent Transaction Interference

**Isolation Levels in PostgreSQL:**

**Read Uncommitted (Not Available in PostgreSQL):**
- Transactions can read uncommitted data from other transactions
- **Problem**: Dirty reads—reading data that may be rolled back
- **Payment Impact**: Could read a balance that's being modified and will be rolled back

**Read Committed (PostgreSQL Default):**
- Transactions can only read committed data
- **Prevents**: Dirty reads
- **Allows**: Non-repeatable reads (same query returns different results)
- **Payment Impact**: Two balance checks in same transaction might see different values

**Repeatable Read:**
- Transactions see consistent snapshot throughout transaction
- **Prevents**: Dirty reads, non-repeatable reads
- **Allows**: Phantom reads (new rows appear)
- **Payment Impact**: Balance remains consistent within transaction, but new transactions might appear

**Serializable (Highest Isolation):**
- Transactions execute as if serially (one after another)
- **Prevents**: All anomalies (dirty reads, non-repeatable reads, phantom reads)
- **Cost**: Highest lock contention, potential deadlocks
- **Payment Impact**: Maximum correctness, but may impact performance

**Our Implementation: Read Committed + Explicit Locking**

We use PostgreSQL's default **Read Committed** isolation level combined with explicit row-level locking:

```python
# Explicit pessimistic lock
user = db.query(User).filter(User.id == user_id).with_for_update().first()
```

**Why This Approach:**

1. **Read Committed is sufficient** because we use explicit locks for critical sections
2. **`SELECT ... FOR UPDATE`** provides stronger guarantees than isolation level alone:
   - Locks the row until transaction commits
   - Prevents other transactions from reading or modifying the locked row
   - Effectively provides serializable behavior for the locked row

3. **Performance vs. Correctness Trade-off**:
   - Serializable: Correct but potentially slow (locks entire table ranges)
   - Read Committed + FOR UPDATE: Correct for our use case, better performance (locks only specific rows)

**Concurrency Scenario Analysis:**

```
Time    Transaction A                    Transaction B
----------------------------------------------------------
T1      BEGIN
T2      SELECT balance FROM users        BEGIN
        WHERE id = 1                      SELECT balance FROM users
        (balance = 1000)                  WHERE id = 1
                                          (balance = 1000)
T3      SELECT ... FOR UPDATE             SELECT ... FOR UPDATE
        WHERE id = 1                      WHERE id = 1
        (Acquires lock)                   (WAITS for lock)
T4      balance -= 100
        balance = 900
T5      COMMIT (releases lock)            (Lock acquired)
T6                                       balance -= 100
                                         balance = 800
T7                                       COMMIT
```

**Without FOR UPDATE**: Both transactions read 1000, both deduct 100, final balance = 800 (incorrect—should be 800, but race condition occurred)

**With FOR UPDATE**: Transaction B waits, reads 900 after A commits, deducts 100, final balance = 800 (correct)

### 1.3 Concurrency Control: Optimistic vs. Pessimistic Locking

#### Optimistic Locking (Versioning)

**Mechanism**: Assume conflicts are rare. Track version numbers, detect conflicts on commit, retry if conflict detected.

**Implementation Pattern:**
```python
# Optimistic locking with version column
class User(Base):
    id: int
    balance: float
    version: int  # Version number

# Update with version check
user = db.query(User).filter(User.id == user_id).first()
original_version = user.version

# ... business logic ...
user.balance -= amount

# Commit with version check
try:
    db.query(User).filter(
        User.id == user_id,
        User.version == original_version
    ).update({
        'balance': user.balance,
        'version': User.version + 1
    })
    db.commit()
except StaleDataError:
    # Version changed - conflict detected
    db.rollback()
    # Retry or return error
```

**Characteristics:**
- **Low Lock Contention**: No locks held during business logic
- **High Throughput**: Multiple transactions can proceed concurrently
- **Conflict Detection**: Detects conflicts at commit time
- **Retry Required**: Must retry on conflict

**When to Use:**
- Low conflict probability
- Long-running transactions
- Read-heavy workloads
- Distributed systems where locking is expensive

#### Pessimistic Locking (SELECT FOR UPDATE)

**Mechanism**: Assume conflicts are likely. Acquire lock early, hold until commit, serialize conflicting operations.

**Implementation Pattern:**
```python
# Pessimistic locking
user = db.query(User).filter(User.id == user_id).with_for_update().first()
# Lock held until transaction commits or rolls back

user.balance -= amount
db.commit()  # Lock released
```

**Characteristics:**
- **High Lock Contention**: Locks held during entire transaction
- **Lower Throughput**: Conflicting transactions must wait
- **Conflict Prevention**: Prevents conflicts rather than detecting them
- **No Retry Needed**: Guaranteed to succeed if lock acquired

**When to Use:**
- High conflict probability
- Short-running transactions
- Write-heavy workloads
- Financial transactions (correctness > performance)

#### Why We Chose Pessimistic Locking for Balance Updates

**Reason 1: Financial Correctness is Non-Negotiable**

In payment systems, **correctness is more important than throughput**. Pessimistic locking provides stronger guarantees:

- **No Retries Needed**: Once lock is acquired, transaction is guaranteed to succeed (assuming no validation failures)
- **Deterministic Behavior**: No race conditions, no need to handle conflict retries
- **Audit Trail**: Clear transaction ordering in database logs

**Reason 2: Balance Updates are High-Conflict Operations**

When multiple charges target the same user account:
- **Optimistic**: Multiple transactions proceed, detect conflict at commit, retry → Unpredictable latency, potential retry storms
- **Pessimistic**: First transaction proceeds, others wait → Predictable behavior, guaranteed ordering

**Reason 3: Short Transaction Duration**

Balance update transactions are **short-lived** (typically < 50ms):
- Lock is held for minimal time
- Waiting transactions experience acceptable latency
- Throughput impact is minimal for typical payment volumes

**Reason 4: Database-Level Guarantees**

`SELECT ... FOR UPDATE` provides database-enforced serialization:
- No application-level coordination needed
- Works correctly even with multiple application instances
- Database handles deadlock detection and resolution

**Trade-off Analysis:**

| Aspect | Optimistic | Pessimistic |
|--------|-----------|-------------|
| **Throughput** | Higher (no waiting) | Lower (waiting) |
| **Latency (no conflict)** | Lower | Higher (lock acquisition) |
| **Latency (conflict)** | Higher (retry overhead) | Lower (wait then proceed) |
| **Correctness Guarantee** | Eventual (after retry) | Immediate |
| **Complexity** | Higher (retry logic) | Lower (simple lock) |
| **Suitable For** | Low conflict, long transactions | High conflict, short transactions |

**Conclusion**: For financial balance updates with high correctness requirements and short transaction duration, pessimistic locking is the appropriate choice.

---

## 2. Architecture Rationale (Architecture Decisions)

### 2.1 FastAPI & Async I/O: Why FastAPI?

#### The GIL (Global Interpreter Lock) Misconception

**Common Misconception**: "Python's GIL prevents true concurrency, so async doesn't help."

**Reality**: The GIL only prevents **CPU-bound** parallelism. For **I/O-bound** operations (which payment systems primarily are), async/await provides significant performance benefits.

**How Async I/O Works in Python:**

```python
# Synchronous (blocking) code
def process_charge():
    user = db.query(User).first()      # Blocks: waits for DB response (~10ms)
    cache_result = redis.get(key)      # Blocks: waits for Redis response (~1ms)
    return response                     # Total: ~11ms of waiting

# With 100 concurrent requests:
# Thread 1: waits 11ms
# Thread 2: waits 11ms (blocked, can't do other work)
# ...
# Thread 100: waits 11ms
# Total time: ~11ms * 100 = 1100ms (sequential waiting)

# Asynchronous (non-blocking) code
async def process_charge():
    user = await db.execute(query)     # Yields control while waiting (~10ms)
    cache_result = await redis.get(key) # Yields control while waiting (~1ms)
    return response                     # Total: ~11ms, but can handle other requests

# With 100 concurrent requests:
# Request 1: yields during DB wait, Request 2-100 can proceed
# All requests yield during I/O, event loop schedules ready operations
# Total time: ~11ms (parallel waiting)
```

**Key Insight**: While waiting for I/O (database, Redis, network), the event loop can process other requests. This is **true concurrency** for I/O-bound workloads.

#### FastAPI's Async Architecture

**FastAPI leverages Python's `asyncio` event loop:**

```python
@app.post("/charge")
async def charge(...):  # async function
    # I/O operations yield control to event loop
    cached_result = await get_cached_transaction(key)  # Non-blocking
    user = await db.execute(query)                      # Non-blocking
    await cache_transaction(key, data)                  # Non-blocking
```

**Event Loop Behavior:**
1. Request arrives → FastAPI schedules async function
2. Function hits `await` → Yields control to event loop
3. Event loop processes other ready requests
4. I/O completes → Function resumes execution
5. Process repeats

**Performance Comparison:**

**Synchronous Framework (Flask, Django):**
- **Thread-per-request model**: Each request requires a thread
- **Thread overhead**: ~1-2MB memory per thread, context switching cost
- **Scalability**: Limited by thread pool size (typically 100-1000 threads)
- **I/O blocking**: Threads blocked during database/Redis calls

**Asynchronous Framework (FastAPI):**
- **Event loop model**: Single thread handles all requests
- **Memory efficient**: ~KB per coroutine, minimal context switching
- **Scalability**: Can handle 10,000+ concurrent connections
- **I/O non-blocking**: Event loop processes other requests during I/O waits

**Real-World Impact for Payment Systems:**

```
Scenario: 1000 concurrent charge requests
Each request: 10ms DB query + 1ms Redis lookup = 11ms I/O time

Synchronous (100 threads):
- 100 requests processed in parallel
- Remaining 900 requests wait in queue
- Total time: ~100ms (10 batches of 100)

Asynchronous (single event loop):
- All 1000 requests processed concurrently
- Event loop interleaves I/O waits
- Total time: ~11ms (all requests complete together)
```

**Why Not Go or Node.js?**

**Go Advantages:**
- True parallelism (goroutines, no GIL)
- Better for CPU-bound tasks
- Lower memory footprint

**Python/FastAPI Advantages:**
- Rich ecosystem (SQLAlchemy, Pydantic)
- Faster development velocity
- Sufficient performance for I/O-bound payment APIs
- Team expertise and maintainability

**Conclusion**: For I/O-bound payment processing APIs, FastAPI's async model provides excellent performance while maintaining Python's development advantages.

### 2.2 Redis as a Lock/Cache: Optimistic Check vs. Distributed Locking

#### Current Implementation: Optimistic Cache Check

**Our Approach:**
```python
# Step 1: Optimistic cache check (no locking)
cached_result = get_cached_transaction(idempotency_key)
if cached_result:
    return cached_result  # Fast path

# Step 2: Database transaction with row lock
existing_transaction = db.query(Transaction)
    .filter(Transaction.idempotency_key == idempotency_key)
    .with_for_update()  # Pessimistic lock at DB level
    .first()
```

**Characteristics:**
- **Cache**: Optimistic (no locking, best-effort)
- **Database**: Pessimistic (row-level lock, authoritative)
- **Consistency Model**: Eventual consistency between cache and database
- **Failure Mode**: Cache miss → Database provides correctness guarantee

#### Alternative: Distributed Locking with Redlock

**Redlock Algorithm (Redis Distributed Lock):**

```python
# Distributed lock implementation
def acquire_lock(key: str, ttl: int) -> bool:
    # Try to acquire lock in majority of Redis instances
    lock_acquired = False
    for redis_instance in redis_instances:
        if redis_instance.set(key, value, nx=True, ex=ttl):
            lock_acquired = True
    
    if lock_acquired_count >= len(redis_instances) / 2 + 1:
        return True  # Lock acquired
    else:
        # Release partial locks
        release_locks()
        return False

# Usage
if acquire_lock(f"lock:{idempotency_key}", ttl=30):
    try:
        # Check cache
        cached_result = redis.get(f"idempotency:{idempotency_key}")
        if cached_result:
            return cached_result
        
        # Process transaction
        process_transaction()
        
        # Write to cache
        redis.set(f"idempotency:{idempotency_key}", result, ex=86400)
    finally:
        release_lock(f"lock:{idempotency_key}")
```

**Comparison:**

| Aspect | Optimistic Check (Current) | Distributed Lock (Redlock) |
|--------|---------------------------|---------------------------|
| **Performance** | Faster (no lock acquisition) | Slower (lock overhead) |
| **Consistency** | Eventual (cache may be stale) | Strong (cache guaranteed fresh) |
| **Complexity** | Lower | Higher (lock management) |
| **Failure Handling** | Graceful (DB fallback) | Complex (lock expiration, deadlocks) |
| **Scalability** | Better (no lock contention) | Worse (lock contention) |
| **Correctness** | DB provides guarantee | Cache provides guarantee |

#### Why We Chose Optimistic Check

**Reason 1: Database as Source of Truth**

Our architecture treats PostgreSQL as the **authoritative source of truth**. Redis cache is a **performance optimization**, not a correctness requirement:

- **Cache Hit**: Fast response, but if cache is wrong, database would catch it on next request
- **Cache Miss**: Slower response, but database provides correct answer
- **Cache Inconsistency**: Tolerable because database always corrects it

**Reason 2: Simpler Failure Modes**

With optimistic check:
- **Redis Down**: System degrades gracefully to database-only mode
- **Cache Stale**: Next request (or TTL expiration) corrects it
- **No Deadlocks**: No distributed lock coordination needed

With distributed lock:
- **Lock Expiration**: Risk of processing same request twice if lock expires
- **Lock Contention**: High concurrency creates lock wait queues
- **Network Partitions**: Redlock requires majority of Redis instances, complex failure scenarios

**Reason 3: Performance Characteristics**

For payment systems, **cache hit rate** is typically 70-80% (many duplicate requests):
- **Optimistic**: 70% of requests get sub-millisecond cache response
- **Distributed Lock**: All requests wait for lock acquisition (even cache hits)

**When Distributed Locking Would Be Appropriate:**

- **Cache as Source of Truth**: If Redis held authoritative data (not our case)
- **Strong Consistency Required**: If cache inconsistency is unacceptable (financial systems prefer DB as source of truth)
- **Single Redis Instance**: Simpler lock implementation (but single point of failure)

**Conclusion**: Our optimistic check approach provides the performance benefits of caching while maintaining database-level correctness guarantees, with simpler failure modes and better scalability.

### 2.3 PostgreSQL as Source of Truth: Why Not MongoDB?

#### Schema Enforcement and Relational Integrity

**PostgreSQL (Relational Database):**

```python
# Schema defined at database level
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    balance: Mapped[float] = mapped_column(nullable=False)

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # Referential integrity
    amount: Mapped[float] = mapped_column(nullable=False)
    idempotency_key: Mapped[Optional[UUID]] = mapped_column(unique=True)  # Unique constraint
```

**Database-Level Guarantees:**
- **Foreign Key Constraints**: Cannot create transaction for non-existent user
- **Unique Constraints**: Database enforces idempotency key uniqueness
- **Type Safety**: Balance must be numeric, cannot be string
- **NOT NULL Constraints**: Required fields cannot be missing

**MongoDB (Document Database):**

```javascript
// Schema defined at application level (optional)
{
  _id: ObjectId("..."),
  user_id: 1,  // No foreign key constraint
  balance: "1000.0",  // Could be string (no type enforcement)
  transactions: []  // Embedded documents
}
```

**Application-Level Validation Only:**
- **No Foreign Keys**: Application must validate user exists
- **No Unique Constraints**: Application must check idempotency key uniqueness
- **Type Flexibility**: Balance could be string, number, or missing
- **Schema Evolution**: Changes require application-level migration logic

#### Financial Ledger Requirements

**Payment systems require strict data integrity:**

**1. Referential Integrity:**
```sql
-- PostgreSQL prevents orphaned transactions
DELETE FROM users WHERE id = 1;
-- ERROR: Foreign key constraint violation
-- Transactions referencing user_id = 1 prevent deletion

-- MongoDB allows orphaned documents
db.users.deleteOne({_id: 1})
// Succeeds, but transactions still reference user_id = 1
// Application must handle orphaned data
```

**2. ACID Transaction Guarantees:**

**PostgreSQL:**
- **Multi-document transactions**: Supported (since MongoDB 4.0)
- **Isolation levels**: Configurable (Read Committed, Serializable)
- **Row-level locking**: `SELECT ... FOR UPDATE` for fine-grained control
- **Mature implementation**: Decades of production use in financial systems

**MongoDB:**
- **Multi-document transactions**: Supported but newer (MongoDB 4.0+, 2018)
- **Isolation levels**: Limited options
- **Document-level locking**: Less granular than row-level
- **Performance impact**: Transactions have higher overhead than PostgreSQL

**3. Audit Trail and Compliance:**

**PostgreSQL:**
- **WAL (Write-Ahead Logging)**: Complete transaction log
- **Point-in-time recovery**: Restore to any transaction
- **Compliance**: SOC 2, PCI DSS certified deployments available
- **Financial industry adoption**: Widely used in banking, fintech

**MongoDB:**
- **Oplog**: Operation log for replication
- **Point-in-time recovery**: Possible but more complex
- **Compliance**: Available but less established in financial sector

#### Query Patterns and Performance

**Payment System Query Patterns:**

**1. Balance Lookup with Transaction History:**
```sql
-- PostgreSQL: Efficient JOIN
SELECT u.balance, t.amount, t.created_at
FROM users u
JOIN transactions t ON u.id = t.user_id
WHERE u.id = 1
ORDER BY t.created_at DESC;

-- Indexes: Primary key on users.id, foreign key index on transactions.user_id
-- Performance: O(log n) with proper indexes
```

**MongoDB Equivalent:**
```javascript
// Option 1: Embedded transactions (denormalized)
db.users.findOne({_id: 1})
// Returns user with embedded transactions array
// Problem: Array grows unbounded, document size limits

// Option 2: Separate collections (normalized)
db.users.findOne({_id: 1})
db.transactions.find({user_id: 1}).sort({created_at: -1})
// Two queries, application-level join
// Problem: No referential integrity, potential inconsistency
```

**2. Idempotency Key Lookup:**
```sql
-- PostgreSQL: Unique index for O(log n) lookup
SELECT * FROM transactions 
WHERE idempotency_key = 'abc-123';
-- Index: CREATE UNIQUE INDEX ON transactions(idempotency_key)
-- Performance: O(log n) with B-tree index
```

**MongoDB:**
```javascript
// Unique index possible
db.transactions.createIndex({idempotency_key: 1}, {unique: true})
db.transactions.findOne({idempotency_key: 'abc-123'})
// Performance: Similar to PostgreSQL
// But: No foreign key to ensure user_id exists
```

#### Why PostgreSQL for Financial Systems

**Industry Standard:**
- **Banking**: PostgreSQL used by major financial institutions
- **Fintech**: Stripe, Square use PostgreSQL for core payment processing
- **Regulatory**: Meets financial regulatory requirements
- **Audit**: Complete transaction logs for compliance

**Maturity and Reliability:**
- **25+ years**: Production-proven in financial systems
- **ACID**: Mature ACID implementation
- **Consistency**: Strong consistency guarantees
- **Recovery**: Proven disaster recovery mechanisms

**Conclusion**: For financial payment systems requiring strict data integrity, referential integrity, ACID guarantees, and regulatory compliance, PostgreSQL is the appropriate choice. MongoDB's schema flexibility and document model are better suited for content management, logging, and other use cases where strict relational integrity is less critical.

---

## 3. Code Implementation Analysis (Line-by-Line Logic)

### 3.1 app/main.py: The Critical Path

Let us trace the complete request lifecycle through the charge endpoint:

#### Phase 1: Authentication

```python
@app.post("/charge", response_model=ChargeResponse, status_code=status.HTTP_200_OK)
async def charge(
    charge_request: ChargeRequest,
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)  # ← Dependency injection
):
```

**Dependency Injection Flow:**
1. FastAPI calls `verify_api_key()` before executing `charge()`
2. `verify_api_key()` extracts `X-API-Key` header from request
3. Validates against `APP_API_KEY` environment variable
4. Raises HTTPException(401) if invalid, otherwise returns API key
5. Only if authentication succeeds does `charge()` function execute

**Why This Order Matters**: Authentication failure prevents any business logic execution, minimizing resource consumption for unauthorized requests.

#### Phase 2: Idempotency Key Extraction

```python
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
```

**Logic Analysis:**
- **Timing Start**: Metrics collection begins immediately to measure total request latency
- **Header Extraction**: `request.headers.get()` returns None if header missing (idempotency optional)
- **UUID Validation**: Ensures idempotency key is valid UUID format (prevents injection, ensures uniqueness)
- **Early Return**: Invalid format returns 400 immediately (no database/Redis calls)

#### Phase 3: Redis Cache Check (Fast Path)

```python
    # Check Redis cache first for idempotency key
    if idempotency_key:
        cached_result = get_cached_transaction(str(idempotency_key))
        if cached_result:
            # Cache hit - return cached response immediately without touching database
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
            
            return ChargeResponse(...)
```

**Critical Path Analysis:**

1. **Cache Lookup**: `get_cached_transaction()` queries Redis with key `idempotency:{uuid}`
   - **If Hit**: Returns cached JSON data (sub-millisecond)
   - **If Miss**: Returns None, proceeds to database
   - **If Error**: Returns None, gracefully degrades to database

2. **Response Reconstruction**: Cached data is JSON, must convert back to Python objects:
   - Status string → `TransactionStatus` enum
   - UUID string → `uuid.UUID` object
   - This conversion ensures type safety in response

3. **Metrics Recording**: Records `idempotent_hit` status and latency
   - **Why Before Return**: Ensures metrics captured even if response serialization fails

4. **Early Return**: Returns immediately, **no database access**
   - **Performance**: Sub-millisecond response time
   - **Database Load**: Zero database queries for cache hits

#### Phase 4: Database Transaction (Safe Path)

```python
    # Cache miss or no idempotency key - proceed with database transaction
    # Start a database transaction
    try:
        # Check for existing transaction with the same idempotency_key within the transaction
        # This ensures concurrency safety - we lock the row if it exists
        if idempotency_key:
            existing_transaction = (
                db.query(Transaction)
                .filter(Transaction.idempotency_key == idempotency_key)
                .with_for_update()  # ← Pessimistic lock
                .first()
            )
```

**Transaction Boundary**: SQLAlchemy session begins transaction implicitly. All database operations until `commit()` or `rollback()` are within single transaction.

**Row-Level Locking**: `with_for_update()` acquires exclusive lock on matching transaction row:
- **If Row Exists**: Lock acquired, other transactions wait
- **If Row Doesn't Exist**: No lock (nothing to lock), proceeds to create new transaction
- **Lock Duration**: Held until transaction commits or rolls back

**Concurrency Scenario:**
```
Time    Request A                          Request B
----------------------------------------------------------
T1      BEGIN TRANSACTION
T2      SELECT ... FOR UPDATE              BEGIN TRANSACTION
        WHERE idempotency_key = 'abc'      SELECT ... FOR UPDATE
        (No row found, no lock)            WHERE idempotency_key = 'abc'
                                            (WAITS - A's transaction active)
T3      INSERT transaction                 (Still waiting)
        idempotency_key = 'abc'
T4      COMMIT (releases implicit lock)    (Lock acquired, row now exists)
T5                                        SELECT returns existing row
T6                                        Return idempotent response
T7                                        COMMIT
```

#### Phase 5: User Balance Update (Atomic Operation)

```python
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
            logger.info(...)
            # Rollback the transaction explicitly
            db.rollback()
            # Record metrics for insufficient balance
            duration = time.time() - start_time
            record_charge_request('insufficient_balance', duration)
            raise HTTPException(...)
        
        # Deduct the amount from user's balance
        user.balance -= amount
        
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
```

**Atomicity Guarantee**: Both `user.balance -= amount` and `db.add(transaction)` are within single transaction:

1. **BEGIN TRANSACTION** (implicit)
2. **Lock User Row** (`with_for_update`)
3. **Validate Balance** (read balance)
4. **Modify Balance** (write balance)
5. **Create Transaction Record** (insert)
6. **COMMIT** (both changes persist together)

**If Any Step Fails**: `ROLLBACK` ensures neither change persists.

**Isolation Guarantee**: `with_for_update()` ensures:
- No other transaction can read or modify user row until this transaction commits
- Prevents race condition where two transactions both read same balance and both proceed

#### Phase 6: Cache Write (Dual-Write Pattern)

```python
        # Refresh to get the latest data
        db.refresh(transaction)
        db.refresh(user)
        
        # Build response
        response = ChargeResponse(...)
        
        # Cache the successful transaction result in Redis
        if idempotency_key:
            cache_data = {...}
            cache_transaction(str(idempotency_key), cache_data)
        
        # Record metrics for successful charge
        duration = time.time() - start_time
        record_charge_request('success', duration)
        
        return response
```

**Dual-Write Problem**: We write to database first, then Redis. What if database succeeds but Redis fails?

### 3.2 The Dual-Write Problem and Eventual Consistency

#### Problem Statement

```python
# Current implementation
db.commit()  # ← Succeeds
cache_transaction(key, data)  # ← Fails (Redis down, network error, etc.)
```

**Inconsistency**: Database has transaction, cache does not. Next request with same idempotency key:
- Cache miss → Database lookup → Finds transaction → Returns idempotent response
- **Correctness**: Maintained (database is source of truth)
- **Performance**: Degraded (cache miss, database query required)

#### Why This Is Acceptable: Eventual Consistency Model

**Our Architecture Tolerates Cache Inconsistency:**

1. **Database is Source of Truth**: Correctness guaranteed by database
2. **Cache is Performance Optimization**: Cache miss degrades performance but not correctness
3. **TTL Strategy**: Cache entries expire after 24 hours, ensuring eventual consistency
4. **Self-Healing**: Next request with same idempotency key will:
   - Cache miss → Database lookup → Cache write (repairs inconsistency)

#### Alternative Solutions and Trade-offs

**Option 1: Transactional Outbox Pattern**

```python
# Write to database with outbox record
db.commit()
outbox_record = Outbox(event_type='transaction_completed', data=cache_data)
db.add(outbox_record)
db.commit()

# Separate process reads outbox and writes to Redis
# Guarantees: Eventually consistent, but adds complexity
```

**Trade-off**: Adds complexity (outbox table, background processor) for stronger consistency guarantee we don't need.

**Option 2: Two-Phase Commit (2PC)**

```python
# Coordinated commit across database and Redis
coordinator.begin_2pc()
db.prepare()
redis.prepare()
coordinator.commit()  # Both commit or both rollback
```

**Trade-off**: High complexity, performance overhead, not supported by Redis. Overkill for our use case.

**Option 3: Write-Through Cache (Synchronous)**

```python
# Write to both in transaction
with db.transaction():
    db.commit()
    redis.set(key, value)  # Must succeed or transaction rolls back
```

**Trade-off**: Redis failure blocks database commit. Unacceptable for payment systems (database correctness > cache performance).

**Our Choice: Best-Effort Cache Write**

```python
db.commit()  # Always succeeds (critical)
try:
    cache_transaction(key, data)  # Best effort
except:
    logger.warning("Cache write failed")  # Log but don't fail
```

**Rationale**:
- **Correctness**: Database commit always succeeds
- **Performance**: Cache write usually succeeds (high success rate)
- **Resilience**: Cache failure doesn't impact payment processing
- **Simplicity**: No complex coordination logic

**TTL Mitigation Strategy:**

Cache entries have 24-hour TTL. This ensures:
- **Stale Data Expiration**: Even if cache write fails initially, entry expires
- **Self-Correction**: Next request (within 24 hours) will cache the result
- **Bounded Inconsistency**: Maximum inconsistency window is 24 hours (acceptable for idempotency use case)

**Conclusion**: Our dual-write approach with best-effort cache write and TTL expiration provides the right balance of performance, correctness, and simplicity for payment systems.

### 3.3 app/auth.py: Dependency Injection Benefits

#### Implementation Analysis

```python
def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI dependency to verify API key from X-API-Key header.
    """
    if not api_key or api_key != APP_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return api_key

@app.post("/charge")
async def charge(..., api_key: str = Depends(verify_api_key)):
    # Endpoint execution requires valid API key
```

#### Why Dependency Injection vs. Alternatives

**Alternative 1: Global State**

```python
# Global state approach
APP_API_KEY = os.getenv("APP_API_KEY")

@app.post("/charge")
async def charge(...):
    api_key = request.headers.get("X-API-Key")
    if api_key != APP_API_KEY:
        raise HTTPException(401)
    # Business logic
```

**Problems:**
- **Testing**: Must mock global variable or set environment variable
- **Coupling**: Endpoint tightly coupled to global state
- **Reusability**: Cannot easily use different auth mechanisms
- **Configuration**: Hard to test with different API keys

**Alternative 2: Decorator Pattern**

```python
# Decorator approach
def require_api_key(f):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key != APP_API_KEY:
            raise HTTPException(401)
        return f(*args, **kwargs)
    return wrapper

@app.post("/charge")
@require_api_key
async def charge(...):
    # Business logic
```

**Problems:**
- **Testing**: Must mock request object or decorator
- **Flexibility**: Hard to conditionally apply (e.g., some endpoints public)
- **Composition**: Difficult to combine multiple decorators
- **FastAPI Integration**: Doesn't leverage FastAPI's dependency system

**Dependency Injection Benefits:**

**1. Testability**

```python
# Easy to test with mock dependency
def test_charge_endpoint():
    def mock_verify_api_key():
        return "valid-key"
    
    # Override dependency
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    
    response = client.post("/charge", ...)
    assert response.status_code == 200
    
    # Cleanup
    app.dependency_overrides.clear()
```

**2. Separation of Concerns**

```python
# Authentication logic isolated
def verify_api_key(...):  # Single responsibility: auth validation

# Business logic isolated
async def charge(...):  # Single responsibility: payment processing
```

**3. Reusability**

```python
# Same auth function used across multiple endpoints
@app.post("/charge")
async def charge(..., api_key: str = Depends(verify_api_key)):
    pass

@app.post("/refund")
async def refund(..., api_key: str = Depends(verify_api_key)):
    pass

@app.get("/transactions")
async def get_transactions(..., api_key: str = Depends(verify_api_key)):
    pass
```

**4. Composition**

```python
# Easy to combine multiple dependencies
async def charge(
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    rate_limiter: bool = Depends(check_rate_limit)
):
    # All dependencies executed in order
```

**5. FastAPI Integration**

FastAPI's dependency injection system provides:
- **Automatic execution**: Dependencies run before endpoint function
- **Error handling**: Dependency exceptions automatically converted to HTTP responses
- **Request context**: Dependencies have access to request object
- **Type safety**: Type hints enable validation and IDE support

**Conclusion**: Dependency injection promotes testability, separation of concerns, reusability, and clean architecture. It is the appropriate pattern for authentication and other cross-cutting concerns in FastAPI applications.

---

## 4. Infrastructure & Observability (DevOps View)

### 4.1 Prometheus Metrics: Why Latency Buckets (Histogram)?

#### The Long Tail Problem

**Average Latency Misconception:**

Consider 100 requests with the following latencies:
- 99 requests: 10ms each
- 1 request: 1000ms (database connection timeout)

**Average Latency**: (99 × 10ms + 1000ms) / 100 = 19.9ms

**Problem**: Average suggests good performance, but 1% of users experience 1-second delays. This is the **long tail problem**.

**Real-World Impact in Payment Systems:**

```
Scenario: 10,000 payment requests per minute
Average latency: 50ms (looks good)
But: 1% of requests (100 requests) take 2 seconds

Impact:
- 100 customers experience 2-second payment delays
- Customer satisfaction: Poor (despite "good" average)
- SLA violation: 99th percentile > 1 second (SLA requirement)
- Business impact: Lost customers, support tickets
```

#### Histogram vs. Average: The Difference

**Average (Mean) Metric:**
```python
# Simple average
total_latency = 0
request_count = 0

def record_latency(latency):
    total_latency += latency
    request_count += 1

average = total_latency / request_count
# Problem: Hides distribution, long tail invisible
```

**Histogram Metric:**
```python
# Histogram with buckets
buckets = [0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]

def record_latency(latency):
    for bucket in buckets:
        if latency <= bucket:
            bucket_counter[bucket].inc()
    total_sum += latency
    total_count += 1

# Enables percentile calculation
p95 = histogram_quantile(0.95, bucket_counters)
p99 = histogram_quantile(0.99, bucket_counters)
```

**Histogram Output:**
```
charge_request_latency_seconds_bucket{le="0.01"} 8500.0
charge_request_latency_seconds_bucket{le="0.05"} 9200.0
charge_request_latency_seconds_bucket{le="0.1"} 9800.0
charge_request_latency_seconds_bucket{le="0.5"} 9950.0
charge_request_latency_seconds_bucket{le="1.0"} 9990.0
charge_request_latency_seconds_bucket{le="2.0"} 9995.0
charge_request_latency_seconds_bucket{le="5.0"} 10000.0
charge_request_latency_seconds_sum 125.5
charge_request_latency_seconds_count 10000.0
```

**Analysis:**
- **Average**: 125.5ms / 10000 = 12.55ms (looks excellent)
- **95th Percentile**: ~0.5 seconds (50 requests exceed 500ms)
- **99th Percentile**: ~1.0 second (10 requests exceed 1 second)
- **Insight**: Long tail problem revealed—1% of requests are slow

#### Why Buckets Matter for Payment Systems

**SLA Requirements:**
- **Average Latency**: < 100ms (easy to meet)
- **95th Percentile**: < 500ms (requires monitoring percentiles)
- **99th Percentile**: < 1 second (critical for payment systems)

**Bucket Selection Strategy:**

Our buckets `[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]` are chosen to:

1. **Capture Cache Hits**: 0.01s (10ms) bucket captures Redis cache hits
2. **Capture Database Queries**: 0.05s (50ms) bucket captures typical database queries
3. **Capture Slow Queries**: 0.1s (100ms) bucket captures slower database operations
4. **SLA Boundaries**: 0.5s and 1.0s buckets align with SLA requirements
5. **Error Detection**: 2.0s+ buckets capture timeouts and errors

**Prometheus Query Examples:**

```promql
# Average latency (less useful)
rate(charge_request_latency_seconds_sum[5m]) / 
rate(charge_request_latency_seconds_count[5m])

# 95th percentile (SLA monitoring)
histogram_quantile(0.95, rate(charge_request_latency_seconds_bucket[5m]))

# 99th percentile (long tail monitoring)
histogram_quantile(0.99, rate(charge_request_latency_seconds_bucket[5m]))

# Percentage of requests exceeding SLA
sum(rate(charge_request_latency_seconds_bucket{le="1.0"}[5m])) / 
sum(rate(charge_request_latency_seconds_bucket{le="+Inf"}[5m])) * 100
```

**Conclusion**: Histograms with appropriate buckets enable percentile-based SLA monitoring, long tail problem detection, and performance optimization targeting the slowest requests. This is essential for payment systems where user experience depends on consistent, predictable latency.

### 4.2 Docker Networking: Internal DNS Resolution

#### How Docker Resolves Service Names

**Docker Compose Configuration:**
```yaml
services:
  app:
    depends_on:
      - db
      - redis
  db:
    image: postgres:15-alpine
  redis:
    image: redis:7-alpine
```

**Internal DNS Resolution:**

When the application container executes:
```python
DATABASE_URL = "postgresql://postgres:postgres@db:5432/picopay"
REDIS_HOST = "redis"
```

Docker's internal DNS resolves:
- `db` → IP address of the `db` container
- `redis` → IP address of the `redis` container

#### Docker Network Architecture

**Default Bridge Network:**

Docker Compose creates a default bridge network for the project:
- **Network Name**: `picopay-payment-engine_default` (project name + `_default`)
- **DNS Server**: Embedded DNS server (127.0.0.11) in each container
- **Service Discovery**: Service names automatically registered as DNS names

**Resolution Process:**

```
Application Container
    │
    │ DNS Query: "db"
    ▼
Docker Embedded DNS (127.0.0.11)
    │
    │ Lookup: Service name "db" → Container IP
    ▼
Returns: 172.18.0.2 (db container IP)
    │
    │ TCP Connection: 172.18.0.2:5432
    ▼
PostgreSQL Container
```

**Network Isolation:**

- **Internal Network**: Containers can communicate using service names
- **External Access**: Only exposed ports (8000, 5433) accessible from host
- **Security**: Database and Redis not exposed externally (only app port 8000)

**Configuration Details:**

```python
# app/database.py
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/picopay")
#                                                                        ^^
#                                                              Service name, not IP

# app/cache.py
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
#                                    ^^^^^^
#                              Service name, not IP
```

**Why Service Names Instead of IPs:**

1. **Dynamic IPs**: Container IPs change on restart
2. **Scalability**: Multiple containers can share service name (load balancing)
3. **Simplicity**: No need to discover or hardcode IP addresses
4. **Portability**: Same configuration works across environments

**Production Considerations:**

In production (Kubernetes, ECS), service discovery works similarly:
- **Kubernetes**: Service names resolve via kube-dns
- **ECS**: Service names resolve via AWS Cloud Map
- **Same Pattern**: Application code unchanged, infrastructure handles resolution

---

## 5. Design Trade-offs & Scalability (The Senior Interview)

### 5.1 Python vs. Go: Migration Analysis

#### Performance Characteristics

**Python (Current Implementation):**
- **I/O-Bound Performance**: Excellent (async/await, event loop)
- **CPU-Bound Performance**: Limited (GIL prevents true parallelism)
- **Memory**: Higher per-request overhead
- **Startup Time**: Slower (interpreter initialization)

**Go:**
- **I/O-Bound Performance**: Excellent (goroutines, efficient scheduler)
- **CPU-Bound Performance**: Excellent (true parallelism, no GIL)
- **Memory**: Lower per-request overhead
- **Startup Time**: Fast (compiled binary)

#### Component Analysis: Which Would Benefit Most?

**1. Request Handling (I/O-Bound)**

**Current (Python/FastAPI):**
```python
async def charge(...):
    cached = await get_cached_transaction(key)  # I/O: Redis
    user = await db.query(...)                  # I/O: PostgreSQL
    await cache_transaction(key, data)          # I/O: Redis
```

**Go Equivalent:**
```go
func charge(...) {
    cached := getCachedTransaction(key)  // I/O: Redis (goroutine)
    user := db.Query(...)               // I/O: PostgreSQL (goroutine)
    cacheTransaction(key, data)         // I/O: Redis (goroutine)
}
```

**Analysis**: Both handle I/O-bound operations well. **Migration benefit: Moderate**
- Go: Lower memory per request, better CPU utilization
- Python: Sufficient performance, better development velocity

**2. JSON Serialization/Deserialization**

**Current (Python/Pydantic):**
```python
charge_request: ChargeRequest  # Pydantic validation
response = ChargeResponse(...)  # Pydantic serialization
```

**Go Equivalent:**
```go
type ChargeRequest struct {
    UserID  int     `json:"user_id"`
    Amount  float64 `json:"amount"`
    Currency string `json:"currency"`
}
// JSON unmarshaling with struct tags
```

**Analysis**: Go's JSON handling is faster (compiled, no reflection overhead). **Migration benefit: Low**
- Performance difference: ~10-20% faster
- Impact: Minimal (JSON processing is < 1% of request time)

**3. Database Query Processing**

**Current (Python/SQLAlchemy):**
```python
user = db.query(User).filter(User.id == user_id).with_for_update().first()
```

**Go Equivalent:**
```go
var user User
err := db.QueryRow("SELECT * FROM users WHERE id = $1 FOR UPDATE", userID).Scan(&user)
```

**Analysis**: Database query time dominates (network + database processing). **Migration benefit: Low**
- Query time: 10-50ms (database processing)
- Application overhead: < 1ms (negligible)

**4. Metrics Collection**

**Current (Python/prometheus-client):**
```python
charge_requests_total.labels(status=status).inc()
charge_request_latency_seconds.observe(duration)
```

**Go Equivalent:**
```go
chargeRequestsTotal.WithLabelValues(status).Inc()
chargeRequestLatencySeconds.Observe(duration)
```

**Analysis**: Metrics collection is CPU-bound (counter increments, histogram updates). **Migration benefit: Low**
- Overhead: < 0.1ms per request
- Impact: Negligible

#### The Answer: CPU-Bound Components Would Benefit Most

**If we had CPU-bound operations, Go would provide significant benefits:**

**Example: Cryptographic Operations**
```python
# Python: CPU-bound, GIL limits parallelism
signature = hmac.new(key, message, hashlib.sha256).digest()
```

```go
// Go: True parallelism, no GIL
signature := hmac.New(sha256.New, key)
signature.Write(message)
result := signature.Sum(nil)
```

**Performance Difference**: Go could be 2-4x faster for CPU-bound crypto operations.

**For Our Payment System:**

**Current Architecture is I/O-Bound:**
- Redis lookups: I/O (network)
- Database queries: I/O (network + disk)
- JSON serialization: Minimal CPU (negligible)
- Metrics: Minimal CPU (negligible)

**Conclusion**: For our current I/O-bound payment processing architecture, **migration to Go would provide minimal performance benefits** (10-20% improvement at best). The development velocity, ecosystem, and team expertise advantages of Python outweigh the performance gains for this use case.

**When Go Migration Would Make Sense:**
- CPU-bound operations (cryptography, data processing)
- Extremely high request volumes (100k+ requests/second)
- Lower memory requirements critical
- Team has Go expertise

### 5.2 Database Scaling: 100k TPS Challenge

#### The Problem: Single PostgreSQL Instance Limits

**PostgreSQL Performance Characteristics:**
- **Maximum Connections**: ~1000-5000 (configurable, but overhead increases)
- **Write Throughput**: ~10k-50k writes/second (depends on hardware, indexes)
- **Read Throughput**: Higher (can scale with read replicas)
- **Single Instance Limit**: ~50k-100k TPS (transaction per second) on high-end hardware

**At 100k TPS, single instance will:**
- Exhaust connection pool
- Hit I/O bottlenecks (disk writes)
- Experience lock contention
- Fail to meet latency SLAs

#### Strategy 1: Database Sharding (Horizontal Partitioning)

**Concept**: Partition data across multiple database instances based on shard key.

**Sharding by User ID:**

```python
# Shard selection function
def get_shard_id(user_id: int, num_shards: int) -> int:
    return user_id % num_shards

# Database connection per shard
shard_connections = {
    0: create_engine("postgresql://shard0/db"),
    1: create_engine("postgresql://shard1/db"),
    2: create_engine("postgresql://shard2/db"),
    # ... 10 shards for 100k TPS
}

# Route request to appropriate shard
def charge(user_id: int, amount: float):
    shard_id = get_shard_id(user_id, num_shards=10)
    db = shard_connections[shard_id]
    # Process transaction on shard
```

**Benefits:**
- **Linear Scalability**: 10 shards = 10x capacity (theoretically)
- **Isolation**: Shard failure affects subset of users
- **Performance**: Each shard handles 10k TPS (manageable)

**Challenges:**

**1. Cross-Shard Transactions:**
```python
# Problem: User 1 (shard 0) sends money to User 2 (shard 1)
# Solution: Two-phase commit or eventual consistency
def transfer(from_user: int, to_user: int, amount: float):
    from_shard = get_shard_id(from_user)
    to_shard = get_shard_id(to_user)
    
    if from_shard == to_shard:
        # Same shard: Single transaction
        process_transfer(from_user, to_user, amount)
    else:
        # Cross-shard: Complex coordination required
        # Option 1: Saga pattern (eventual consistency)
        # Option 2: Two-phase commit (strong consistency, complex)
```

**2. Shard Rebalancing:**
- Adding/removing shards requires data migration
- Hot shards (popular users) may need special handling
- Shard key selection critical (must distribute evenly)

**3. Query Complexity:**
```sql
-- Simple query becomes complex
SELECT SUM(amount) FROM transactions WHERE user_id IN (1, 2, 3, ...);
-- Must query all shards, aggregate results
```

**4. Idempotency Key Uniqueness:**
```python
# Problem: Idempotency key must be unique across all shards
# Solution: Global idempotency key service or consistent hashing
def get_idempotency_shard(idempotency_key: str) -> int:
    # Hash idempotency key to determine shard
    return hash(idempotency_key) % num_shards
```

**When Sharding Makes Sense:**
- Very high write volume (100k+ TPS)
- Data naturally partitions (user-based sharding)
- Cross-shard operations rare
- Team has sharding expertise

#### Strategy 2: Read Replicas (Master-Slave Replication)

**Concept**: Single write master, multiple read replicas for scaling reads.

**Architecture:**
```
Write Master (PostgreSQL Primary)
    │
    │ Streaming Replication
    ├──► Read Replica 1
    ├──► Read Replica 2
    └──► Read Replica 3
```

**Implementation:**
```python
# Write to master
write_db = create_engine("postgresql://master/db")

# Read from replicas (load balanced)
read_dbs = [
    create_engine("postgresql://replica1/db"),
    create_engine("postgresql://replica2/db"),
    create_engine("postgresql://replica3/db"),
]

def get_user_balance(user_id: int):
    # Read from replica (load balanced)
    db = random.choice(read_dbs)
    return db.query(User).filter(User.id == user_id).first().balance

def charge(user_id: int, amount: float):
    # Write to master
    user = write_db.query(User).filter(User.id == user_id).with_for_update().first()
    user.balance -= amount
    write_db.commit()
```

**Benefits:**
- **Read Scaling**: 3 replicas = 3x read capacity
- **High Availability**: Replica can promote to master on failure
- **Geographic Distribution**: Replicas in different regions reduce latency

**The Critical Problem: Replication Lag**

**Replication Lag Scenario:**
```
Time    Master                    Replica 1              Request
--------------------------------------------------------------
T1      BEGIN
T2      UPDATE users              (not yet replicated)
        SET balance = 900
        WHERE id = 1
T3      COMMIT
T4                                  (replication in progress, lag: 50ms)
T5                                                  Read from Replica 1
                                                    SELECT balance
                                                    FROM users WHERE id = 1
                                                    Returns: 1000 (STALE!)
T6                                  (replication completes)
T7                                  balance = 900 (now correct)
```

**Why This Is Dangerous for Balance Checks:**

```python
# Dangerous: Reading balance from replica
def charge(user_id: int, amount: float):
    # Read from replica (fast, but may be stale)
    balance = read_db.query(User).filter(User.id == user_id).first().balance
    
    if balance >= amount:
        # Write to master
        write_db.query(User).filter(User.id == user_id).update({
            'balance': balance - amount  # ← Uses stale balance!
        })
        # Problem: Balance may have changed on master
```

**Solution: Always Read from Master for Balance Updates**

```python
def charge(user_id: int, amount: float):
    # MUST read from master for balance check
    user = write_db.query(User).filter(User.id == user_id).with_for_update().first()
    
    if user.balance >= amount:
        user.balance -= amount
        write_db.commit()
    
    # Safe: Read from replica for non-critical reads
    transaction_history = read_db.query(Transaction).filter(
        Transaction.user_id == user_id
    ).all()  # OK: Historical data, eventual consistency acceptable
```

**When Read Replicas Make Sense:**
- Read-heavy workload (90% reads, 10% writes)
- Read operations can tolerate eventual consistency
- Write operations always use master
- Geographic distribution needed

**For Payment Systems:**
- **Balance Checks**: Must use master (strong consistency required)
- **Transaction History**: Can use replicas (eventual consistency acceptable)
- **Analytics Queries**: Can use replicas (read-only, eventual consistency acceptable)

#### Strategy 3: Hybrid Approach (Sharding + Read Replicas)

**Architecture:**
```
Shard 0 (Master) ──► Shard 0 Replica 1, Replica 2
Shard 1 (Master) ──► Shard 1 Replica 1, Replica 2
Shard 2 (Master) ──► Shard 2 Replica 1, Replica 2
...
Shard 9 (Master) ──► Shard 9 Replica 1, Replica 2
```

**Benefits:**
- **Write Scaling**: 10 shards handle 100k TPS (10k TPS per shard)
- **Read Scaling**: 2 replicas per shard = 3x read capacity
- **High Availability**: Replica promotion per shard
- **Isolation**: Shard failure affects subset of users

**Complexity:**
- **Very High**: Requires shard management, replica management, routing logic
- **Team Expertise**: Requires senior database engineers
- **Operational Overhead**: Monitoring, alerting, failover procedures

#### Recommended Scaling Path

**Phase 1: Optimize Single Instance (Current)**
- Connection pooling optimization
- Query optimization and indexing
- Hardware scaling (CPU, memory, SSD)
- **Target**: 10k-20k TPS

**Phase 2: Read Replicas**
- Add 2-3 read replicas
- Route analytics and history queries to replicas
- Keep balance checks on master
- **Target**: 20k-50k TPS (read scaling)

**Phase 3: Sharding (If Needed)**
- Implement user-based sharding
- 10-20 shards for 100k+ TPS
- Global idempotency key service
- **Target**: 100k+ TPS

**Conclusion**: For 100k TPS, database sharding is likely necessary, but read replicas can provide intermediate scaling. The critical consideration is that **balance checks must always use the master database** to avoid replication lag issues that could cause incorrect balance deductions.

---

## Summary: Key Takeaways for Senior Engineering

1. **Idempotency is a Financial Correctness Requirement**: Not optional—prevents double-spending and regulatory violations.

2. **ACID Properties Provide Strong Guarantees**: Atomicity ensures all-or-nothing operations, isolation prevents race conditions, and explicit locking provides fine-grained control.

3. **Pessimistic Locking is Appropriate for Financial Transactions**: Correctness > performance for balance updates, and short transaction duration minimizes lock contention.

4. **FastAPI's Async Model Excels at I/O-Bound Workloads**: Despite GIL, async/await provides true concurrency for database and cache operations.

5. **Redis Cache is a Performance Optimization, Not a Correctness Requirement**: Database remains source of truth, cache inconsistencies are tolerable with TTL expiration.

6. **PostgreSQL is the Right Choice for Financial Systems**: Schema enforcement, referential integrity, and ACID guarantees are essential for payment processing.

7. **Dependency Injection Promotes Testability and Maintainability**: FastAPI's dependency system enables clean separation of concerns.

8. **Histograms Reveal Long Tail Problems**: Percentile-based metrics are essential for SLA monitoring in payment systems.

9. **Docker Service Discovery Simplifies Configuration**: Service names resolve automatically via internal DNS.

10. **Scaling Requires Careful Architecture**: Sharding and read replicas each have trade-offs, and balance checks must use master database to avoid replication lag issues.

---

**Document Version**: 1.0.0  
**Last Updated**: December 2025  
**Target Audience**: Engineers transitioning to senior-level architecture understanding


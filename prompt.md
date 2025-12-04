
# Prompt input log

- Step 1: Environment Setup (Environment)
I want to build a payment gateway backend using Python FastAPI, PostgreSQL, and Docker. Please create a docker-compose.yml file. It should include an app service for FastAPI and a db service for PostgreSQL, configured with a volume for persistent data storage. Also, create the initial directory structure for the FastAPI project and a basic requirements.txt containing FastAPI, Uvicorn, SQLAlchemy, and Psycopg2-binary.


- Step 2: Core Logic Implementation (The Core)
Implement a POST /charge API endpoint in the FastAPI application. This API should accept user_id, amount (float), and currency (str) in the request body. Define SQLAlchemy 2.0 style models for User (id, balance) and Transaction (id, user_id, amount, status). Crucially, use a database transaction to ensure that balance deduction and transaction record creation are performed as a single Atomic operation. If the balance is insufficient, return a 400 Bad Request and the transaction must be rolled back.

- Step 3: Idempotency Feature (The Interview Weapon)
Add Idempotency logic to the POST /charge endpoint. If a client includes an Idempotency-Key (UUID) in the request header, this key must be stored in the Transaction model.If a request with the same Idempotency-Key already exists and has a successful status ($\text{status}=\text{success}$), the system should immediately return the previous successful transaction result with a 200 OK without processing the charge or modifying the balance again.Implement the logic to check for the Idempotency-Key within the database transaction to ensure concurrency safety.


- Step 4: Testing & Verification (The Verification) 
Write a Python script using the requests library and Python's concurrent.futures module to simulate a concurrency test.

Specify one user_id and simulate sending 10 concurrent POST /charge requests across separate threads, all using the same amount and the identical Idempotency-Key.

The script should print the final User balance and query the database to print the count of successful transaction records.

The final output must prove that the balance was deducted only once and only one transaction record was created, verifying the successful implementation of idempotency.


- Step 5: 핵심 기능 검증 및 증명 (Verification)
Run the entire project environment using docker-compose up. Then, execute the setup_test_user.py script to initialize a user with a balance of 1000. Finally, run the test_idempotency.py script and output the results. Verify that 10 concurrent requests with the same Idempotency-Key result in the balance being deducted only once, and only one successful transaction record being created.


- Step 6: 유지보수성 및 확장성 확보 (Code Quality)
Refactor the database session dependency injection in main.py and database.py to follow the FastAPI dependency injection best practices more cleanly (e.g., using yield for context management).

Also, implement robust logging (using Python's standard logging module) in the /charge endpoint.

Specifically, log the following events at the INFO level:

Successful new charge: Include the Transaction ID and User ID.

Idempotency hit (prevented duplicate): Include the Idempotency-Key and the returned Transaction ID.

Insufficient balance failure (HTTP 400): Include the User ID and requested Amount.


- Step 7: DevOps & Scalability
Create a simplified deployment guide in the README.md or a new DEPLOY.md file. The guide should outline the steps to deploy the FastAPI application container and the PostgreSQL database (using an external managed service like AWS RDS or a container) onto a cloud environment (e.g., using a simple service like AWS EC2 with Docker or a basic CI/CD pipeline concept).


- Step 8
Introduce a Redis caching layer to the PicoPay architecture to optimize performance.

Specifically, modify the POST /charge API to check for the Idempotency-Key in Redis before querying PostgreSQL.

Cache Hit: If the Idempotency-Key is found in Redis, immediately return the cached successful transaction response (HTTP 200) without touching the database.

Cache Miss/New Request: Proceed to the PostgreSQL transaction as currently implemented.

Cache Write: Upon a successful new charge (after the PostgreSQL transaction is committed), write the transaction result (including status and ID) to Redis using the Idempotency-Key as the key, with a sensible TTL (Time-To-Live) of 24 hours.

Update docker-compose.yml to include a redis service and update requirements.txt with the necessary Python Redis library (e.g., redis).


- Step 9:
Implement a simple API Key authentication mechanism for the POST /charge endpoint using a FastAPI Dependency.

The API Key should be passed via the X-API-Key HTTP header.

The key should be validated against a secret stored in an environment variable (e.g., APP_API_KEY).

If the key is missing or invalid, return a 401 Unauthorized error.

Update the docker-compose.yml to include the APP_API_KEY environment variable.


- Step 10:

Integrate a basic Prometheus metrics collection library (e.g., prometheus_client) into the FastAPI application.

Create a new endpoint, GET /metrics, to expose the raw Prometheus metrics.

Instrument the application to track two key metrics: charge_requests_total (a Counter) and charge_request_latency_seconds (a Histogram or Summary).

Track both successful and failed requests in the counter, using a label like status='success' or status='idempotent_hit'.


Optional

- Image Size

Refactor the existing Dockerfile to use a multi-stage build process. Use a builder stage for dependencies and a smaller base image (e.g., python:3.11-slim or python:3.11-alpine) for the final application image to reduce the overall deployment size.


- Report

All planned system architecture components—PostgreSQL for data consistency, Redis for performance, API Key for authentication, and Prometheus metrics for observability—have been successfully implemented and verified.

The final step is to create a comprehensive REPORT.md file in the root directory. This document must professionally summarize the entire project's technical architecture, core engineering challenges, and business value achieved. Eliminate all emojis and casual language.

The report must contain the following sections:

1. Architecture Overview: Include a high-level system diagram illustrating the flow between the FastAPI application, Redis, PostgreSQL, and the Prometheus metrics endpoint.

2. Data Consistency & Idempotency: Detail the technical implementation ensuring ACID properties via PostgreSQL transactions and the Idempotency-Key handling optimized by the Redis caching layer.

3. Observability & Security: Explain the rationale and implementation of the Prometheus metrics (including tracked labels like idempotent_hit) and the API Key authentication mechanism.

4. Verification Summary: Present the key findings from the concurrency test (e.g., "Balance deducted only once, 1 successful transaction record created for 10 concurrent requests") as empirical proof of the system's stability.


- Readme

Create a new, comprehensive README.md file designed for a professional technical audience (e.g., a hiring manager or tech lead). The tone must be professional, formal, and technical.

The README must focus on the system's architecture and the complex engineering problems solved, structured as follows:

1. Project Title & Tagline: A concise, strong tagline (e.g., "A Robust, Idempotent Payment Gateway Backend").

2. The Challenge Solved: Clearly state the problem—preventing double-spending, ensuring ACID properties, and handling high concurrency—that the system addresses.

3. Core Architecture Overview: List the full technology stack (FastAPI, PostgreSQL, Redis, Prometheus, Docker).

4. Killer Features (Engineering Focus): Highlight the key technical achievements in bullet points:

    - Data Integrity: Atomicity via PostgreSQL Transactions.

    - Scalability & Idempotency: Low-latency duplicate request prevention using Redis caching.

    - Observability: Prometheus metrics instrumentation for monitoring service health and latency.

    - Security: API Key Authentication.

5. Getting Started: Provide clear, minimal steps to run the project (mentioning docker-compose up for development).

6. Documentation Link: Reference the comprehensive DEPLOY.md and REPORT.md files for detailed setup and technical analysis.
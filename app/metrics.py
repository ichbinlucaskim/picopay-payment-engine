from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
import logging

logger = logging.getLogger(__name__)

# Counter for tracking total charge requests
charge_requests_total = Counter(
    'charge_requests_total',
    'Total number of charge requests',
    ['status']  # Labels: 'success', 'failed', 'idempotent_hit', 'insufficient_balance'
)

# Histogram for tracking charge request latency
charge_request_latency_seconds = Histogram(
    'charge_request_latency_seconds',
    'Charge request latency in seconds',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]  # Buckets in seconds
)


def record_charge_request(status: str, duration: float):
    """
    Record charge request metrics.
    
    Args:
        status: Request status ('success', 'failed', 'idempotent_hit', 'insufficient_balance')
        duration: Request duration in seconds
    """
    charge_requests_total.labels(status=status).inc()
    charge_request_latency_seconds.observe(duration)
    logger.debug(f"Recorded metrics: status={status}, duration={duration:.4f}s")


def get_metrics():
    """
    Get Prometheus metrics in text format.
    
    Returns:
        bytes: Prometheus metrics in text format
    """
    return generate_latest()


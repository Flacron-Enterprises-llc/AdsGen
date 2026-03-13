"""
Queue manager for background jobs using Redis Queue (RQ).
"""
import os
from typing import Optional, Dict, Any
import logging

# Optional imports for Redis/RQ
# rq raises ValueError on Windows (no 'fork' multiprocessing context)
try:
    import redis
    from rq import Queue
    REDIS_AVAILABLE = True
except (ImportError, ValueError):
    REDIS_AVAILABLE = False
    redis = None
    Queue = None

logger = logging.getLogger(__name__)

# Redis connection
redis_conn = None
queue = None


def init_queue(redis_url: Optional[str] = None):
    """Initialize Redis connection and queue."""
    global redis_conn, queue
    
    if not REDIS_AVAILABLE:
        logger.debug("Redis/RQ not available — running without background queue")
        redis_conn = None
        queue = None
        return False
    
    try:
        # Priority: parameter > REDIS_URL env > host/port env vars
        connection_url = redis_url or os.getenv('REDIS_URL')
        if connection_url:
            # Handle both redis://redis:6379/0 and redis://localhost:6379/0 formats
            redis_conn = redis.from_url(connection_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
        else:
            # Try to connect to Redis using host/port
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_db = int(os.getenv('REDIS_DB', 0))
            redis_password = os.getenv('REDIS_PASSWORD', None)
            
            redis_conn = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
        
        # Test connection
        redis_conn.ping()
        
        # Create queue
        queue = Queue('ads_generator', connection=redis_conn)
        
        logger.info("Redis queue initialized successfully")
        return True
        
    except Exception as e:
        logger.warning(f"Redis not available, using in-memory fallback: {e}")
        redis_conn = None
        queue = None
        return False


def enqueue_job(job_function, *args, **kwargs):
    """Enqueue a job and return job ID. Runs synchronously if no workers available."""
    if queue and redis_conn:
        # Check if workers are actually available
        if not has_active_workers():
            logger.warning("No active workers detected, running job synchronously")
            result = job_function(*args, **kwargs)
            return {'status': 'completed', 'result': result, 'synchronous': True}
        
        try:
            # Use 5 minute timeout to ensure jobs complete quickly
            job = queue.enqueue(job_function, *args, **kwargs, job_timeout='5m')
            return job.id
        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            # Fallback to synchronous
            result = job_function(*args, **kwargs)
            return {'status': 'completed', 'result': result, 'synchronous': True, 'error': str(e)}
    else:
        # Fallback: run synchronously
        logger.warning("Queue not available, running job synchronously")
        result = job_function(*args, **kwargs)
        return {'status': 'completed', 'result': result, 'synchronous': True}


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get status of a job by ID."""
    if not queue:
        return {'status': 'unknown', 'error': 'Queue not initialized'}
    
    try:
        from rq.job import Job
        job = Job.fetch(job_id, connection=redis_conn)
        
        status = {
            'id': job.id,
            'status': job.get_status(),
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'ended_at': job.ended_at.isoformat() if job.ended_at else None,
        }
        
        if job.is_finished:
            status['result'] = job.result
        elif job.is_failed:
            status['error'] = str(job.exc_info) if job.exc_info else 'Job failed'
        
        return status
        
    except Exception as e:
        return {'status': 'not_found', 'error': str(e)}


def has_active_workers() -> bool:
    """Check if there are active workers processing jobs."""
    global redis_conn
    if not redis_conn:
        return False
    
    try:
        # Check if any workers are registered in Redis
        worker_keys = redis_conn.keys('rq:worker:*')
        return len(worker_keys) > 0
    except Exception:
        return False


def is_queue_available() -> bool:
    """Check if queue is available."""
    return queue is not None and redis_conn is not None


"""
Database manager for PostgreSQL connection and operations.
"""
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2.pool import SimpleConnectionPool
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Connection pool
_connection_pool: Optional[SimpleConnectionPool] = None


def init_db_pool(minconn=1, maxconn=10):
    """Initialize database connection pool."""
    global _connection_pool
    
    if _connection_pool is not None:
        return _connection_pool
    
    try:
        db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'adsgenerator'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }
        
        _connection_pool = SimpleConnectionPool(
            minconn, maxconn,
            **db_config
        )
        
        logger.info("Database connection pool initialized")
        return _connection_pool
        
    except Exception as e:
        logger.debug(f"Database not available (optional): {e}")
        return None


@contextmanager
def get_db_connection():
    """Get database connection from pool."""
    pool = init_db_pool()
    if pool is None:
        raise Exception("Database pool not initialized")
    
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)


def init_database():
    """Initialize database schema."""
    schema_path = Path(__file__).parent / 'schema.sql'
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                    cur.execute(schema_sql)
                conn.commit()
                logger.info("Database schema initialized successfully")
                return True
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        return False


def is_db_available() -> bool:
    """Check if database is available."""
    try:
        pool = init_db_pool()
        if pool is None:
            return False
        conn = pool.getconn()
        conn.close()
        return True
    except Exception:
        return False


class CampaignDB:
    """Database operations for campaigns."""
    
    @staticmethod
    def create_campaign(campaign_data: Dict[str, Any]) -> Optional[int]:
        """Create a new campaign and return its ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO campaigns (name, brand_name, competitor_name, zipcode, 
                                             industry, audience_type, offer_type, goal,
                                             scheduled_at, timezone, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        campaign_data.get('name'),
                        campaign_data.get('brand_name'),
                        campaign_data.get('competitor_name'),
                        campaign_data.get('zipcode'),
                        campaign_data.get('industry'),
                        campaign_data.get('audience_type'),
                        campaign_data.get('offer_type'),
                        campaign_data.get('goal'),
                        campaign_data.get('scheduled_at'),
                        campaign_data.get('timezone'),
                        campaign_data.get('status', 'draft')
                    ))
                    result = cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"Error creating campaign: {e}")
            return None
    
    @staticmethod
    def get_campaign(campaign_id: int) -> Optional[Dict[str, Any]]:
        """Get campaign by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
                    result = cur.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting campaign: {e}")
            return None


class AdVariantDB:
    """Database operations for ad variants."""
    
    @staticmethod
    def create_ad_variants(campaign_id: int, ads: List[Dict[str, Any]]) -> List[int]:
        """Create ad variants for a campaign."""
        variant_ids = []
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    for ad in ads:
                        cur.execute("""
                            INSERT INTO ad_variants (campaign_id, headline, ad_text, cta, hashtags, quality_score)
                            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                            RETURNING id
                        """, (
                            campaign_id,
                            ad.get('headline', ''),
                            ad.get('ad_text', ''),
                            ad.get('cta', ''),
                            json.dumps(ad.get('hashtags', [])),
                            ad.get('quality_score')
                        ))
                        result = cur.fetchone()
                        if result:
                            variant_ids.append(result[0])
            return variant_ids
        except Exception as e:
            logger.error(f"Error creating ad variants: {e}")
            return variant_ids
    
    @staticmethod
    def get_ad_variants_for_campaign(campaign_id: int) -> List[Dict[str, Any]]:
        """Get all ad variants for a campaign."""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM ad_variants WHERE campaign_id = %s ORDER BY id", (campaign_id,))
                    results = cur.fetchall()
                    return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting ad variants: {e}")
            return []


class RecipientDB:
    """Database operations for recipients."""
    
    @staticmethod
    def create_recipients(campaign_id: int, recipients: List[Dict[str, Any]]) -> List[int]:
        """Create recipients for a campaign."""
        recipient_ids = []
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    for recipient in recipients:
                        cur.execute("""
                            INSERT INTO recipients (campaign_id, name, email, phone, channel, tags)
                            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                            ON CONFLICT DO NOTHING
                            RETURNING id
                        """, (
                            campaign_id,
                            recipient.get('name', ''),
                            recipient.get('email'),
                            recipient.get('phone'),
                            recipient.get('channel'),  # 'sms' or 'email'
                            json.dumps(recipient.get('tags', []))
                        ))
                        result = cur.fetchone()
                        if result:
                            recipient_ids.append(result[0])
            return recipient_ids
        except Exception as e:
            logger.error(f"Error creating recipients: {e}")
            return recipient_ids


class SendDB:
    """Database operations for sends."""
    
    @staticmethod
    def create_send(campaign_id: int, ad_variant_id: int, recipient_id: int,
                   channel: str, status: str = 'pending') -> Optional[int]:
        """Create a send record."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO sends (campaign_id, ad_variant_id, recipient_id, channel, status, sent_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        RETURNING id
                    """, (campaign_id, ad_variant_id, recipient_id, channel, status))
                    result = cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"Error creating send: {e}")
            return None
    
    @staticmethod
    def update_send_status(send_id: int, status: str, error_message: Optional[str] = None):
        """Update send status."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    if status == 'delivered':
                        cur.execute("""
                            UPDATE sends SET status = %s, delivered_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (status, send_id))
                    else:
                        cur.execute("""
                            UPDATE sends SET status = %s, error_message = %s
                            WHERE id = %s
                        """, (status, error_message, send_id))
        except Exception as e:
            logger.error(f"Error updating send status: {e}")


class EventDB:
    """Database operations for events."""
    
    @staticmethod
    def create_event(send_id: int, event_type: str, event_data: Dict[str, Any] = None):
        """Create an event record."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO events (send_id, event_type, event_data)
                        VALUES (%s, %s, %s::jsonb)
                    """, (send_id, event_type, json.dumps(event_data or {})))
        except Exception as e:
            logger.error(f"Error creating event: {e}")


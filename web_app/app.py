"""
Flask web application for AdsCompetitor.
Provides a web interface for generating and sending ads.
"""

import os
import sys
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env file from project root
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from: {env_path}")
except ImportError:
    # dotenv not installed, will use system environment variables
    pass

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from ai_generation_layer import AIGenerationLayer
from input_layer import InputLayer, InputType
from processing_layer import ProcessingLayer
from notification_layer import NotificationLayer
from notification_layer.models.notification_types import NotificationType
from notification_layer.exceptions import NotificationError
from notification_layer.utils import validate_phone_number, validate_email, normalize_phone_number

# Optional queue imports
try:
    from jobs.queue_manager import init_queue, enqueue_job, get_job_status, is_queue_available, has_active_workers
    from jobs.job_handlers import generate_ads_job, send_notifications_job
    QUEUE_MODULE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Queue system not available: {e}")
    QUEUE_MODULE_AVAILABLE = False
    init_queue = lambda: False
    enqueue_job = lambda *args, **kwargs: {'status': 'completed', 'result': {}, 'synchronous': True}
    get_job_status = lambda job_id: {'status': 'unknown', 'error': 'Queue not available'}
    is_queue_available = lambda: False
    has_active_workers = lambda: False
    generate_ads_job = None
    send_notifications_job = None

# Get the directory where app.py is located
app_dir = Path(__file__).parent

app = Flask(__name__, 
            template_folder=str(app_dir / 'templates'),
            static_folder=str(app_dir / 'static'))
app.secret_key = os.getenv('SECRET_KEY', 'adscompetitor-secret-key-change-in-production')
CORS(app)

# Initialize queue system
queue_available = False
if QUEUE_MODULE_AVAILABLE:
    try:
        queue_available = init_queue()
    except Exception as e:
        print(f"Warning: Failed to initialize queue: {e}")
        queue_available = False

# Initialize database (optional)
try:
    from database.db_manager import init_db_pool, init_database, is_db_available
    db_pool = init_db_pool()
    if db_pool and is_db_available():
        # Initialize schema if needed
        init_database()
        print("Database initialized successfully")
    else:
        print("Warning: Database not available, continuing without persistence")
except ImportError:
    print("Warning: Database module not available, continuing without persistence")
except Exception as e:
    print(f"Warning: Failed to initialize database: {e}, continuing without persistence")

# Initialize layers (lazy loading)
ai_layer = None
notification_layer = None
input_layer = None
processing_layer = None


def get_ai_layer():
    """Get or initialize AI Generation Layer."""
    global ai_layer
    if ai_layer is None:
        try:
            ai_layer = AIGenerationLayer()
        except Exception as e:
            raise Exception(f"Failed to initialize AI Generation Layer: {e}")
    return ai_layer


def get_notification_layer():
    """Get or initialize Notification Layer."""
    global notification_layer
    if notification_layer is None:
        try:
            notification_layer = NotificationLayer()
        except Exception as e:
            # If notifications aren't configured, return None instead of failing
            # This allows the app to work for ad generation even without notification setup
            print(f"Warning: Notification Layer not available: {e}")
            print("Note: You can still generate ads. Notifications require Twilio/SendGrid credentials.")
            return None
    return notification_layer


def get_input_layer():
    """Get or initialize Input Layer."""
    global input_layer
    if input_layer is None:
        try:
            input_layer = InputLayer()
        except Exception as e:
            raise Exception(f"Failed to initialize Input Layer: {e}")
    return input_layer


def get_processing_layer():
    """Get or initialize Processing Layer."""
    global processing_layer
    if processing_layer is None:
        try:
            processing_layer = ProcessingLayer()
        except Exception as e:
            raise Exception(f"Failed to initialize Processing Layer: {e}")
    return processing_layer


@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/api/validate/phone', methods=['POST'])
def validate_phone():
    """Validate phone number."""
    data = request.json
    phone = data.get('phone', '')
    
    is_valid = validate_phone_number(phone)
    normalized = normalize_phone_number(phone) if is_valid else phone
    
    return jsonify({
        'valid': is_valid,
        'normalized': normalized if is_valid else phone
    })


@app.route('/api/validate/email', methods=['POST'])
def validate_email_endpoint():
    """Validate email address."""
    data = request.json
    email = data.get('email', '')
    
    is_valid = validate_email(email)
    
    return jsonify({
        'valid': is_valid
    })


@app.route('/api/parse-competitor-url', methods=['POST'])
def parse_competitor_url():
    """Parse competitor URL to extract basic information."""
    print("\n[API] POST /api/parse-competitor-url")
    try:
        data = request.json
        print(f"[API]   payload: {data}")
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400
        
        # Basic URL parsing (in production, use a proper web scraping library)
        # Extract domain name
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Extract potential business name from domain
        business_name = domain.split('.')[0].replace('-', ' ').replace('_', ' ').title()
        
        # For now, return basic info (in production, use web scraping)
        return jsonify({
            'success': True,
            'competitor_name': business_name,
            'domain': domain,
            'message': 'Basic info extracted. For detailed analysis, manual entry recommended.'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/generate', methods=['POST'])
def generate_ads():
    """Generate ads from competitor data (background job)."""
    print("\n[STEP 2] POST /api/generate  ──────────────────────────")
    try:
        data = request.json
        print(f"[STEP 2] Input data: {json.dumps(data, indent=2)}")
        
        # Use background job if queue is available
        if queue_available:
            job_id = enqueue_job(generate_ads_job, data)
            # Check if job was enqueued or run synchronously (fallback)
            if isinstance(job_id, dict) and job_id.get('synchronous'):
                # Job ran synchronously (fallback)
                result = job_id.get('result', {})
                if result.get('success'):
                    session['generated_ads'] = result.get('ads', [])
                    session['competitor_data'] = data
                    session['campaign_id'] = result.get('campaign_id')
                return jsonify(result)
            else:
                # Job was queued
                return jsonify({
                    'success': True,
                    'job_id': job_id,
                    'status': 'queued'
                })
        else:
            # Fallback to synchronous execution
            result = generate_ads_job(data)
            if result.get('success'):
                session['generated_ads'] = result['ads']
                session['competitor_data'] = data
                session['campaign_id'] = result.get('campaign_id')
                print(f"[STEP 2] ✓ Generated {len(result['ads'])} ads  (cached={result.get('cached', False)})")
            else:
                print(f"[STEP 2] ✗ Generation failed: {result.get('error')}")
            return jsonify(result)

    except Exception as e:
        print(f"[STEP 2] ✗ Exception: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/send', methods=['POST'])
def send_ads():
    """Send generated ads to users (background job)."""
    print("\n[STEP 4] POST /api/send  ──────────────────────────────")
    try:
        data = request.json
        print(f"[STEP 4] SMS users   : {data.get('sms_users', [])}")
        print(f"[STEP 4] Email users : {data.get('email_users', [])}")
        print(f"[STEP 4] Ads count   : {len(data.get('ads', []))}")
        
        # Get generated ads from session or request
        ads = data.get('ads', session.get('generated_ads', []))
        if not ads:
            return jsonify({
                'success': False,
                'error': 'No ads provided. Please generate ads first.'
            }), 400
        
        sms_users = data.get('sms_users', [])
        email_users = data.get('email_users', [])
        
        if not sms_users and not email_users:
            return jsonify({
                'success': False,
                'error': 'No users provided. Please add at least one phone number or email.'
            }), 400
        
        # Get campaign_id from session (stored during generation) or request
        campaign_id = session.get('campaign_id') or data.get('campaign_id')
        
        # Prepare job data
        job_data = {
            'campaign_id': campaign_id,
            'sms_users': sms_users,
            'email_users': email_users,
            'ads': ads
        }
        
        # Use background job if queue is available
        if queue_available:
            job_id = enqueue_job(send_notifications_job, job_data)
            # Check if job was enqueued or run synchronously
            if isinstance(job_id, dict) and job_id.get('synchronous'):
                # Job ran synchronously (fallback)
                result = job_id.get('result', {})
                return jsonify(result)
            else:
                # Job was queued
                return jsonify({
                    'success': True,
                    'job_id': job_id,
                    'status': 'queued'
                })
        else:
            # Fallback to synchronous execution
            result = send_notifications_job(job_data)
            if result.get('success'):
                summary = result.get('summary', {})
                print(f"[STEP 4] ✓ Send complete — summary: {summary}")
            else:
                print(f"[STEP 4] ✗ Send failed: {result.get('error')}")
            return jsonify(result)

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[STEP 4] ✗ Exception in send_ads: {str(e)}")
        print(f"[STEP 4] Traceback:\n{error_trace}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/job/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get job status by ID."""
    try:
        status = get_job_status(job_id)
        return jsonify({
            'success': True,
            'job': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get notification provider status and queue status."""
    print("\n[API] GET /api/status")
    try:
        notification = get_notification_layer()
        notification_status = {}
        if notification is None:
            notification_status = {
                'overall_enabled': False,
                'providers': {},
                'message': 'Notifications not configured. Set up Twilio/SendGrid credentials to enable.'
            }
        else:
            notification_status = notification.get_provider_status()
        
        return jsonify({
            'success': True,
            'status': notification_status,
            'queue_available': is_queue_available()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print("=" * 60)
    print("AdsCompetitor Web Application")
    print("=" * 60)
    print("\nStarting server...")
    print("Open your browser to: http://localhost:5000")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    
    port = int(os.getenv('PORT', 5001))  # Use port 5001 if 5000 is busy
    app.run(debug=True, host='0.0.0.0', port=port)

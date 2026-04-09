"""
Flask web application for AdsCompetitor.
Provides a web interface for generating and sending ads.
"""

import os
import sys
import json
import time
from datetime import timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env file from project root
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        # override=True: local .env wins over empty/stale OS env vars (e.g. FIREBASE_CREDENTIALS_JSON).
        load_dotenv(env_path, override=True)
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
except (ImportError, ValueError) as e:
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
# Returning from Stripe is a top-level GET; Lax is correct for http://localhost (do not set Secure on http).
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.getenv('SESSION_COOKIE_SECURE', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
CORS(app)

# Reverse proxies (Render, Railway, Heroku) terminate TLS; without this, request.url_root is http://… internally.
if os.getenv('TRUST_PROXY_HEADERS', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


def _public_base_url():
    """
    Origin for Stripe success/cancel URLs (must match the host the user sees in the browser).

    - If PUBLIC_APP_URL host differs from the incoming Host (www vs apex, etc.), we use the
      request URL so the session cookie after Stripe matches the tab that started checkout.
    - If the app still sees http:// behind Render but PUBLIC_APP_URL is https and same host,
      prefer PUBLIC_APP_URL so Stripe gets a public https URL.
    """
    req_base = request.url_root.rstrip('/')
    env_base = (os.getenv('PUBLIC_APP_URL') or os.getenv('APP_BASE_URL') or '').strip().rstrip('/')
    if not env_base:
        return req_base
    try:
        from urllib.parse import urlparse
        eu = urlparse(env_base if '://' in env_base else f'https://{env_base}')
        ru = urlparse(req_base + '/')
        env_host = (eu.netloc or '').lower().split('@')[-1].split(':')[0]
        req_host = (request.host or '').lower().split(':')[0]
        if env_host and req_host and env_host != req_host:
            print(
                f"[stripe] PUBLIC_APP_URL host {env_host!r} != request Host {req_host!r}; "
                f"using request URL for checkout return (avoids losing session after payment)."
            )
            return req_base
        if ru.scheme == 'http' and eu.scheme == 'https' and env_host == req_host:
            return env_base.rstrip('/')
    except Exception:
        pass
    return env_base.rstrip('/')


def _safe_next_after_login(url: str):
    """Allow only internal paths for post-login redirect (open-redirect safe)."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u.startswith('/') or u.startswith('//'):
        return None
    path = u.split('?')[0].split('#')[0]
    if path == '/dashboard':
        return '/dashboard'
    if path == '/choose-plan':
        return '/choose-plan'
    return None


# Firebase client config (for login/signup pages). Server verification uses firebase_admin.
def get_firebase_config():
    api_key = os.getenv('FIREBASE_API_KEY', '')
    if not api_key:
        return None
    return {
        'apiKey': api_key,
        'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN', ''),
        'projectId': os.getenv('FIREBASE_PROJECT_ID', ''),
        'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET', ''),
        'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID', ''),
        'appId': os.getenv('FIREBASE_APP_ID', ''),
    }

def _normalize_credentials_path(raw: str) -> str:
    """Strip whitespace and surrounding quotes from .env paths (common misconfiguration)."""
    if not raw:
        return ''
    s = raw.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1]
    return s.strip()


# Initialize Firebase Admin SDK for server-side token verification (optional)
# On Render/Heroku: use FIREBASE_CREDENTIALS_JSON (paste the whole service account JSON as one line).
_firebase_app = None
try:
    import firebase_admin
    from firebase_admin import credentials

    def _attach_firebase_app(app_obj):
        global _firebase_app
        _firebase_app = app_obj

    def _firebase_init_certificate(cred_arg, label: str):
        """cred_arg is a dict or path string; Certificate() accepts both."""
        try:
            app_obj = firebase_admin.initialize_app(credentials.Certificate(cred_arg))
            print(f"Firebase Admin initialized from {label}")
            return app_obj
        except ValueError as e:
            err = str(e).lower()
            if "already exists" in err or "already been initialized" in err:
                existing = firebase_admin.get_app()
                print(f"Firebase Admin: reusing existing default app ({label})")
                return existing
            raise

    def _parse_service_account_json(raw: str):
        """Parse JSON; retry with literal \\n -> newline for some PaaS env encodings."""
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json.loads(raw.replace("\\n", "\n"))

    # Option 1: JSON string in env (Render, Azure, IBM Cloud, etc.)
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
    if cred_json:
        try:
            cred_dict = _parse_service_account_json(cred_json)
            _attach_firebase_app(_firebase_init_certificate(cred_dict, "FIREBASE_CREDENTIALS_JSON"))
        except Exception as e:
            print(f"Firebase Admin (FIREBASE_CREDENTIALS_JSON) failed: {e}")
            import traceback
            traceback.print_exc()

    # Option 2: File path (local dev)
    if _firebase_app is None:
        cred_path = _normalize_credentials_path(
            os.getenv("FIREBASE_CREDENTIALS_PATH", "") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        )
        if cred_path:
            p = Path(cred_path)
            if p.is_file():
                try:
                    _attach_firebase_app(_firebase_init_certificate(str(p.resolve()), "FIREBASE_CREDENTIALS_PATH"))
                except Exception as e:
                    print(f"Firebase Admin (credentials file) failed: {e}")
            else:
                print(
                    "Firebase Admin: credentials file not found at FIREBASE_CREDENTIALS_PATH / "
                    f"GOOGLE_APPLICATION_CREDENTIALS: {p.resolve()}\n"
                    "  Fix: download the service account JSON from Firebase Console (Project settings > "
                    "Service accounts > Generate new private key), save it, and set FIREBASE_CREDENTIALS_PATH "
                    "to that file (or set FIREBASE_CREDENTIALS_JSON to the JSON contents)."
                )
    if _firebase_app is None:
        try:
            _attach_firebase_app(firebase_admin.get_app())
            print("Firebase Admin: attached via get_app() (already initialized in this process)")
        except ValueError:
            pass
except Exception as e:
    print(f"Firebase Admin not initialized (optional): {e}")
    import traceback
    traceback.print_exc()

# Subscription store (Firestore) for plan gating
try:
    from .subscription_store import (
        init_subscription_store,
        has_active_plan,
        get_subscription,
        set_plan,
        list_all_subscriptions,
        update_subscription_status,
        update_subscription_plan,
        get_pricing,
        set_pricing,
    )
    from .campaign_store import list_all_campaigns, get_usage_stats
    init_subscription_store()
except Exception as e:
    print(f"Subscription/Campaign store init failed: {e}")
    has_active_plan = lambda email: False
    get_subscription = lambda email: None
    def set_plan(email, plan, stripe_customer_id=None, stripe_subscription_id=None):
        return False
    list_all_subscriptions = lambda: []
    list_all_campaigns = lambda: []
    get_usage_stats = lambda: {'sms': 0, 'email': 0, 'sms_sent': 0, 'email_sent': 0}
    update_subscription_status = lambda e, s: False
    update_subscription_plan = lambda e, p: False
    get_pricing = lambda: {}
    set_pricing = lambda d: None

# Session fallback when Firestore read lags or fails after a verified write (Stripe / free plan).
_PLAN_GATE_MAX_AGE_SEC = 7 * 24 * 3600


def user_has_active_plan(email: str) -> bool:
    """True if Firestore has an active subscription, or a recent verified plan_gate for this user."""
    e = (email or '').strip().lower()
    if not e:
        return False
    if has_active_plan(e):
        session.pop('plan_gate', None)
        session.modified = True
        return True
    pg = session.get('plan_gate') or {}
    if (pg.get('email') or '').strip().lower() != e:
        return False
    if pg.get('plan') not in ('free', 'starter', 'pro'):
        return False
    if time.time() - float(pg.get('ts') or 0) > _PLAN_GATE_MAX_AGE_SEC:
        return False
    return True


def set_plan_gate(email: str, plan: str) -> None:
    e = (email or '').strip().lower()
    if e and plan in ('free', 'starter', 'pro'):
        session['plan_gate'] = {'email': e, 'plan': plan, 'ts': time.time()}
        session.modified = True


# Initialize queue system (optional)
queue_available = False
if QUEUE_MODULE_AVAILABLE:
    try:
        queue_available = init_queue()
    except Exception:
        queue_available = False

# Initialize database (optional)
try:
    from database.db_manager import init_db_pool, init_database, is_db_available
    db_pool = init_db_pool()
    if db_pool and is_db_available():
        init_database()
        print("Database initialized successfully")
except (ImportError, Exception):
    pass

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
    """Landing: login/signup. Admins go to /admin; others with plan to dashboard; else choose-plan."""
    if session.get('logged_in'):
        email = (session.get('user_email') or '').strip().lower()
        if email in get_admin_emails():
            return redirect('/admin')
        return redirect('/dashboard' if user_has_active_plan(email) else '/choose-plan')
    return render_template('landing.html')


@app.route('/dashboard')
def dashboard():
    """Generator dashboard. Requires login and an active plan (free/starter/pro)."""
    if not session.get('logged_in'):
        return redirect('/login')
    email = (session.get('user_email') or '').strip().lower()
    if not user_has_active_plan(email):
        return redirect('/choose-plan')
    is_admin = email in get_admin_emails()
    return render_template('index.html', is_admin=is_admin)


@app.route('/login', methods=['GET'])
def login():
    """Login page. Uses Firebase Auth on the client if Firebase is configured."""
    if session.get('logged_in'):
        email = (session.get('user_email') or '').strip().lower()
        if email in get_admin_emails():
            return redirect('/admin')
        return redirect('/dashboard' if user_has_active_plan(email) else '/choose-plan')
    firebase_config = get_firebase_config()
    login_next = _safe_next_after_login(request.args.get('next', ''))
    pay_err = (request.args.get('pay_err') or '').strip()
    pay_ok = (request.args.get('pay_ok') or '').strip()
    pay_err_messages = {
        'missing_session': 'Checkout session missing. Open the link from Stripe again or pick a plan.',
        'no_email': 'We could not read your email from the payment. Contact support.',
        'plan_unknown': 'Payment completed but we could not read your plan. Contact support with your receipt.',
        'save_failed': 'Payment may have succeeded but saving your plan failed. Enable Firestore, then sign in — or contact support.',
        'not_paid': 'That checkout was not completed. Try paying again.',
    }
    login_banner_text = None
    login_banner_error = False
    if pay_ok:
        login_banner_text = 'Payment received. Sign in with the same email you used at checkout to open the dashboard.'
        login_banner_error = False
    elif pay_err:
        login_banner_text = pay_err_messages.get(pay_err, 'Something went wrong after payment. Try signing in, or contact support.')
        login_banner_error = True
    return render_template(
        'login.html',
        firebase_config=firebase_config,
        login_next=login_next,
        login_banner_text=login_banner_text,
        login_banner_error=login_banner_error,
    )


@app.route('/signup', methods=['GET'])
def signup():
    """Signup page. Uses Firebase Auth on the client if Firebase is configured."""
    if session.get('logged_in'):
        email = (session.get('user_email') or '').strip().lower()
        if email in get_admin_emails():
            return redirect('/admin')
        return redirect('/dashboard' if user_has_active_plan(email) else '/choose-plan')
    firebase_config = get_firebase_config()
    return render_template('signup.html', firebase_config=firebase_config)


@app.route('/auth/firebase', methods=['POST'])
def auth_firebase():
    """
    Exchange Firebase ID token for a session.
    Expects JSON: { "id_token": "..." } or form id_token.
    """
    if _firebase_app is None:
        return jsonify({'success': False, 'error': 'Firebase not configured on server'}), 503
    id_token = None
    body = request.get_json(silent=True) or {}
    id_token = (body.get('id_token') or request.form.get('id_token') or '').strip()
    next_path = _safe_next_after_login((body.get('next') or request.form.get('next') or '').strip())
    if not id_token:
        return jsonify({'success': False, 'error': 'id_token required'}), 400
    try:
        from firebase_admin import auth as fb_auth
        try:
            decoded = fb_auth.verify_id_token(id_token, clock_skew_seconds=60)
        except TypeError:
            decoded = fb_auth.verify_id_token(id_token)
        email = (decoded.get('email') or '').strip().lower()
        name = (decoded.get('name') or decoded.get('email', '') or '').strip()
        if not email:
            return jsonify({'success': False, 'error': 'Invalid token'}), 400
        session['user_email'] = email
        session['user_name'] = name
        session['logged_in'] = True
        session.permanent = True
        admin_list = get_admin_emails()
        if email in admin_list:
            redirect_to = '/admin'
        else:
            if user_has_active_plan(email):
                redirect_to = next_path if next_path else '/dashboard'
            else:
                redirect_to = '/choose-plan'
            if admin_list:
                print(f"[auth] Login email={email!r} not in ADMIN_EMAILS={admin_list!r} -> redirect {redirect_to}")
        return jsonify({'success': True, 'redirect': redirect_to})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 401


@app.route('/logout')
def logout():
    """Clear session and redirect to home."""
    session.pop('logged_in', None)
    session.pop('user_email', None)
    session.pop('user_name', None)
    session.pop('plan_gate', None)
    return redirect('/')


@app.route('/pricing')
def pricing():
    """Pricing plans and usage-based billing."""
    logged_in = bool(session.get('logged_in'))
    return render_template('pricing.html', logged_in=logged_in)


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/about')
def about():
    return render_template('about.html')


def _stripe_metadata_dict(checkout) -> dict:
    """Normalize Stripe Checkout Session metadata to a plain dict."""
    try:
        md = checkout.get('metadata') if hasattr(checkout, 'get') else None
        if md is None:
            md = getattr(checkout, 'metadata', None)
        if not md:
            return {}
        if isinstance(md, dict):
            return dict(md)
        if hasattr(md, 'to_dict'):
            return dict(md.to_dict())
        return dict(md)
    except Exception:
        return {}


def _resolve_paid_plan_from_checkout(checkout) -> str:
    """Return 'starter' or 'pro' from session metadata or Stripe Price IDs on line items / subscription."""
    md = _stripe_metadata_dict(checkout)
    p = (md.get('plan') or '').strip().lower()
    if p in ('starter', 'pro'):
        return p
    starter_price = (os.getenv('STRIPE_PRICE_STARTER') or '').strip()
    pro_price = (os.getenv('STRIPE_PRICE_PRO') or '').strip()
    if not starter_price and not pro_price:
        return ''
    try:
        line_items = getattr(checkout, 'line_items', None)
        line_data = getattr(line_items, 'data', None) if line_items else None
        if line_data:
            for li in line_data:
                price = getattr(li, 'price', None)
                pid = getattr(price, 'id', None) if price else None
                if pid and pid == starter_price:
                    return 'starter'
                if pid and pro_price and pid == pro_price:
                    return 'pro'
    except Exception as e:
        print(f"[payment_success] plan from line_items: {e}")
    try:
        sub = checkout.get('subscription') if hasattr(checkout, 'get') else getattr(checkout, 'subscription', None)
        if sub and not isinstance(sub, str):
            items = getattr(getattr(sub, 'items', None), 'data', None)
            if items:
                for si in items:
                    price = getattr(si, 'price', None)
                    pid = getattr(price, 'id', None) if price else None
                    if pid and pid == starter_price:
                        return 'starter'
                    if pid and pro_price and pid == pro_price:
                        return 'pro'
    except Exception as e:
        print(f"[payment_success] plan from subscription items: {e}")
    try:
        sub = checkout.get('subscription') if hasattr(checkout, 'get') else getattr(checkout, 'subscription', None)
        if sub and not isinstance(sub, str):
            smd = getattr(sub, 'metadata', None)
            if smd:
                if hasattr(smd, 'to_dict'):
                    smd = smd.to_dict()
                elif not isinstance(smd, dict):
                    smd = dict(smd)
                p = (smd.get('plan') or '').strip().lower()
                if p in ('starter', 'pro'):
                    return p
    except Exception as e:
        print(f"[payment_success] plan from subscription metadata: {e}")
    return ''


@app.route('/choose-plan')
def choose_plan():
    """Mandatory plan selection after signup. Requires login. Admins go to /admin. Free = select; Starter/Pro = pay via Stripe."""
    if not session.get('logged_in'):
        return redirect('/login')
    email = (session.get('user_email') or '').strip().lower()
    if email in get_admin_emails():
        return redirect('/admin')
    if user_has_active_plan(email):
        return redirect('/dashboard')
    stripe_publishable = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
    err = (request.args.get('err') or '').strip()
    err_messages = {
        'missing_session': 'Missing payment session. Return from Stripe checkout or contact support.',
        'session_mismatch': 'This payment does not match your logged-in account. Log in with the same email you used at checkout.',
        'no_email': 'Could not confirm your email from the payment. Contact support.',
        'plan_unknown': 'Payment completed but we could not determine your plan. Contact support with your receipt.',
        'save_failed': 'Payment succeeded but saving your plan failed. Enable Firestore for your Firebase project and ensure the server has credentials, then use “Select Free” or pay again, or contact support.',
        'not_paid': 'Payment was not completed. Try again or choose another plan.',
    }
    plan_error = err_messages.get(err)
    return render_template(
        'choose_plan.html',
        stripe_publishable_key=stripe_publishable,
        plan_error=plan_error,
    )


@app.route('/payment-success')
def payment_success():
    """
    After Stripe Checkout: verify session, write plan to Firestore, then redirect.
    Does NOT require a Flask session first — returning from Stripe often drops the session cookie;
    we use Checkout client_reference_id / customer_email, then send the user to login if needed.
    """
    session_id = request.args.get('session_id', '').strip()
    if not session_id:
        return redirect(url_for('login', next='/choose-plan', pay_err='missing_session'))
    secret = os.getenv('STRIPE_SECRET_KEY', '')
    if not secret:
        return redirect(url_for('login', next='/dashboard', pay_err='save_failed'))
    try:
        import stripe
        stripe.api_key = secret
        try:
            checkout = stripe.checkout.Session.retrieve(
                session_id,
                expand=['subscription', 'line_items.data.price'],
            )
        except Exception as e:
            print(f"[payment_success] retrieve with line_items expand failed, retrying: {e}")
            checkout = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
        ps = checkout.get('payment_status')
        st = checkout.get('status')
        if ps not in ('paid', 'no_payment_required') and st != 'complete':
            return redirect(url_for('login', next='/choose-plan', pay_err='not_paid'))

        ref = (checkout.get('client_reference_id') or '').strip().lower()
        cust_email = (checkout.get('customer_email') or '').strip().lower()
        session_email = (session.get('user_email') or '').strip().lower()
        logged_in = bool(session.get('logged_in'))

        if logged_in and session_email:
            if ref and ref != session_email:
                print(f"[payment_success] client_reference_id mismatch ref={ref!r} session={session_email!r}")
                return redirect(url_for('choose_plan', err='session_mismatch'))
            email = session_email
        else:
            email = ref or cust_email

        if not email:
            return redirect(url_for('login', next='/dashboard', pay_err='no_email'))

        plan = _resolve_paid_plan_from_checkout(checkout)
        if plan not in ('starter', 'pro'):
            print(f"[payment_success] unresolved plan; metadata={_stripe_metadata_dict(checkout)}")
            return redirect(url_for('login', next='/choose-plan', pay_err='plan_unknown'))

        sub = checkout.get('subscription')
        if isinstance(sub, str):
            stripe_sub_id = sub
        elif sub is not None:
            stripe_sub_id = getattr(sub, 'id', None)
        else:
            stripe_sub_id = None

        cust_id = checkout.get('customer')
        if isinstance(cust_id, str):
            stripe_customer_id = cust_id
        elif cust_id is not None:
            stripe_customer_id = getattr(cust_id, 'id', None)
        else:
            stripe_customer_id = checkout.get('customer_id')

        ok = set_plan(
            email,
            plan,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_sub_id,
        )
        if not ok:
            print(
                f"[payment_success] set_plan returned False for {email!r} plan={plan!r} — "
                "Firestore may not be enabled. Stamping plan_gate so user can still access the dashboard."
            )

        # Stripe confirmed the payment — stamp plan_gate regardless of Firestore result.
        # This lets the user access the dashboard even if Firestore is not yet enabled/reachable.
        set_plan_gate(email, plan)

        if logged_in and session_email == email:
            return redirect('/dashboard')

        # Not logged in (common: Stripe opened in same tab but session cookie was dropped).
        return redirect(url_for('login', next='/dashboard', pay_ok='1'))
    except Exception as e:
        print(f"[payment_success] Error: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('login', next='/dashboard', pay_err='save_failed'))


@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe Checkout Session for Starter or Pro. Requires login."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Login required'}), 401
    data = request.json or {}
    plan = (data.get('plan') or '').strip().lower()
    if plan not in ('starter', 'pro'):
        return jsonify({'error': 'Invalid plan'}), 400
    secret = (os.getenv('STRIPE_SECRET_KEY') or '').strip()
    price_id = (os.getenv('STRIPE_PRICE_STARTER') if plan == 'starter' else os.getenv('STRIPE_PRICE_PRO') or '').strip()
    if not secret or not price_id:
        return jsonify({'error': 'Stripe not configured. Set STRIPE_SECRET_KEY and STRIPE_PRICE_STARTER/STRIPE_PRICE_PRO in .env'}), 503
    email = (session.get('user_email') or '').strip().lower()
    base = _public_base_url()
    success_url = (os.getenv('STRIPE_SUCCESS_URL') or '').strip() or (base + '/payment-success')
    cancel_url = (os.getenv('STRIPE_CANCEL_URL') or '').strip() or (base + '/choose-plan')
    try:
        import stripe
        stripe.api_key = secret
        session_obj = stripe.checkout.Session.create(
            mode='subscription',
            customer_email=email,
            client_reference_id=email,
            line_items=[{'price': price_id, 'quantity': 1}],
            success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=cancel_url,
            metadata={'plan': plan},
            subscription_data={'metadata': {'plan': plan}},
        )
        return jsonify({'url': session_obj.url})
    except Exception as e:
        err = str(e)
        print(f"[create_checkout_session] Stripe error: {err}")
        if 'recurring' in err.lower() or 'subscription' in err.lower():
            err = "Stripe price must be recurring (monthly). Create a recurring price in Stripe and set STRIPE_PRICE_STARTER / STRIPE_PRICE_PRO."
        elif 'No such price' in err or 'invalid' in err.lower():
            err = "Invalid Stripe Price ID. Check STRIPE_PRICE_STARTER and STRIPE_PRICE_PRO in .env match your Stripe product prices."
        return jsonify({'error': err}), 200


@app.route('/api/select-free-plan', methods=['POST'])
def select_free_plan():
    """Mark current user as on Free plan. Requires login."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Login required'}), 401
    email = (session.get('user_email') or '').strip().lower()
    ok = set_plan(email, 'free')
    if not ok:
        print(f"[select_free_plan] Firestore write failed for {email!r}; stamping plan_gate anyway")
    set_plan_gate(email, 'free')
    return jsonify({'success': True, 'redirect': '/dashboard'})


@app.route('/api/stripe-webhook', methods=['POST'])
def stripe_webhook():
    """
    Stripe webhook: handles checkout.session.completed to persist plan in Firestore.
    Set STRIPE_WEBHOOK_SECRET on Render (from Stripe Dashboard → Webhooks).
    This is the reliable server-side fallback — it fires even when the browser tab drops the session.
    """
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get('Stripe-Signature', '')
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
    if not payload:
        return jsonify({'error': 'No payload'}), 400
    event = None
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')
        if webhook_secret:
            try:
                event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
            except stripe.error.SignatureVerificationError as e:
                print(f"[webhook] Invalid signature: {e}")
                return jsonify({'error': 'Invalid signature'}), 400
        else:
            event = json.loads(payload)
            print("[webhook] STRIPE_WEBHOOK_SECRET not set — accepting unverified (dev only)")
    except Exception as e:
        print(f"[webhook] Parse error: {e}")
        return jsonify({'error': 'Parse error'}), 400

    if event.get('type') == 'checkout.session.completed':
        obj = event.get('data', {}).get('object', {})
        if hasattr(obj, 'get'):
            ps = obj.get('payment_status')
            st = obj.get('status')
        else:
            ps = getattr(obj, 'payment_status', None)
            st = getattr(obj, 'status', None)
        if ps in ('paid', 'no_payment_required') or st == 'complete':
            md = {}
            raw_md = getattr(obj, 'metadata', None) if not hasattr(obj, 'get') else obj.get('metadata')
            if raw_md:
                md = dict(raw_md) if not isinstance(raw_md, dict) else raw_md
            plan = (md.get('plan') or '').strip().lower()
            if plan not in ('starter', 'pro'):
                if hasattr(obj, 'get'):
                    ref = (obj.get('client_reference_id') or '').lower()
                    cust_email = (obj.get('customer_email') or '').lower()
                else:
                    ref = (getattr(obj, 'client_reference_id', None) or '').lower()
                    cust_email = (getattr(obj, 'customer_email', None) or '').lower()
                starter_price = (os.getenv('STRIPE_PRICE_STARTER') or '').strip()
                pro_price = (os.getenv('STRIPE_PRICE_PRO') or '').strip()
                line_items_url = f"https://api.stripe.com/v1/checkout/sessions/{getattr(obj, 'id', obj.get('id', ''))}/line_items"
                try:
                    import stripe as stripe_mod
                    sess_id = getattr(obj, 'id', None) or obj.get('id', '')
                    li = stripe_mod.checkout.Session.list_line_items(sess_id, limit=5)
                    for item in (li.get('data') if hasattr(li, 'get') else getattr(li, 'data', [])):
                        price = getattr(item, 'price', None)
                        pid = getattr(price, 'id', None) if price else None
                        if pid == starter_price:
                            plan = 'starter'
                            break
                        if pid and pro_price and pid == pro_price:
                            plan = 'pro'
                            break
                except Exception as li_err:
                    print(f"[webhook] line_items lookup failed: {li_err}")
            email = (md.get('email') or '')
            if not email:
                if hasattr(obj, 'get'):
                    email = (obj.get('client_reference_id') or obj.get('customer_email') or '').strip().lower()
                else:
                    email = (getattr(obj, 'client_reference_id', None) or getattr(obj, 'customer_email', None) or '').strip().lower()
            if email and plan in ('starter', 'pro'):
                try:
                    if hasattr(obj, 'get'):
                        sub_id = obj.get('subscription')
                        cust_id = obj.get('customer')
                    else:
                        sub_id = getattr(obj, 'subscription', None)
                        cust_id = getattr(obj, 'customer', None)
                    set_plan(
                        email, plan,
                        stripe_customer_id=cust_id if isinstance(cust_id, str) else getattr(cust_id, 'id', None),
                        stripe_subscription_id=sub_id if isinstance(sub_id, str) else getattr(sub_id, 'id', None),
                    )
                    print(f"[webhook] checkout.session.completed → set_plan({email!r}, {plan!r})")
                except Exception as e:
                    print(f"[webhook] set_plan failed: {e}")
            else:
                print(f"[webhook] skipped: email={email!r} plan={plan!r}")
    return jsonify({'status': 'ok'})


@app.route('/api/plan-status')
def plan_status():
    """Diagnostic: current user's plan from Firestore + session plan_gate."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Login required'}), 401
    email = (session.get('user_email') or '').strip().lower()
    sub = get_subscription(email)
    pg = session.get('plan_gate') or {}
    return jsonify({
        'email': email,
        'firestore_plan': sub.get('plan') if sub else None,
        'firestore_status': sub.get('status') if sub else None,
        'plan_gate': pg.get('plan') if pg else None,
        'plan_gate_email': pg.get('email') if pg else None,
        'has_active_plan': user_has_active_plan(email),
    })


@app.route('/api/subscription-status')
def subscription_status():
    """Return { has_plan, plan } for current user."""
    if not session.get('logged_in'):
        return jsonify({'has_plan': False, 'plan': None})
    email = (session.get('user_email') or '').strip().lower()
    sub = get_subscription(email)
    return jsonify({'has_plan': sub is not None, 'plan': sub.get('plan') if sub else None})


@app.route('/api/usage')
def api_usage():
    """Return current period usage and limits for the logged-in user."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Login required'}), 401
    try:
        from .usage_limits import get_usage, get_overage_cost
        email = (session.get('user_email') or '').strip().lower()
        usage = get_usage(email)
        overage = get_overage_cost(email)
        usage['overage_cost'] = overage
        return jsonify(usage)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/charge-overage', methods=['POST'])
def charge_overage():
    """Charge current period overage to Stripe (adds to next invoice). Starter/Pro only."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Login required'}), 401
    try:
        from .billing import charge_overage_stripe
        email = (session.get('user_email') or '').strip().lower()
        result = charge_overage_stripe(email)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Admin ─────────────────────────────────────────────────────────────────

def get_admin_emails():
    """Comma-separated list of admin emails from env."""
    raw = (os.getenv('ADMIN_EMAILS') or '').strip()
    # Split by comma or newline, normalize to lowercase
    emails = []
    for part in raw.replace('\n', ',').split(','):
        e = part.strip().lower()
        if e:
            emails.append(e)
    return emails


def is_admin():
    """True if current user can access admin (email in list or verified with admin password)."""
    if not session.get('logged_in'):
        return False
    email = (session.get('user_email') or '').strip().lower()
    if email in get_admin_emails():
        return True
    return session.get('admin_verified') is True


def admin_required(f):
    """Decorator: require login and (email in ADMIN_EMAILS or correct ADMIN_PASSWORD)."""
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        if not is_admin():
            if request.is_json or request.headers.get('Accept', '').startswith('application/json'):
                return jsonify({'error': 'Forbidden'}), 403
            return redirect('/admin/verify')
        return f(*args, **kwargs)
    return wrapped


@app.route('/admin/verify', methods=['GET', 'POST'])
def admin_verify():
    """Enter admin password to access admin (when email not in ADMIN_EMAILS)."""
    if not session.get('logged_in'):
        return redirect('/login')
    if is_admin():
        return redirect('/admin')
    admin_pass = (os.getenv('ADMIN_PASSWORD') or '').strip()
    if not admin_pass:
        return redirect('/')
    if request.method == 'POST':
        if (request.form.get('password') or '').strip() == admin_pass:
            session['admin_verified'] = True
            return redirect('/admin')
        return render_template('admin_verify.html', error='Incorrect password.')
    return render_template('admin_verify.html')


@app.route('/admin')
@admin_required
def admin_index():
    return render_template('admin/index.html')


def _format_firebase_timestamp(ts):
    """Convert Firebase timestamp (ms or seconds) to readable string."""
    if ts is None or (isinstance(ts, (int, float)) and ts <= 0):
        return ''
    try:
        from datetime import datetime
        if ts > 1e12:
            ts = ts / 1000.0  # milliseconds
        return datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M UTC')
    except Exception:
        return str(ts)


@app.route('/admin/users')
@admin_required
def admin_users():
    users = []
    if _firebase_app:
        try:
            from firebase_admin import auth as fb_auth
            # UserRecord has metadata.creation_timestamp (Python SDK) or user_metadata (Node naming)
            page = fb_auth.list_users(max_results=1000)
            it = getattr(page, 'iterate_all', None)
            if it:
                for u in it():
                    meta = getattr(u, 'user_metadata', None) or getattr(u, 'metadata', None)
                    ts = getattr(meta, 'creation_timestamp', None) if meta else None
                    users.append({
                        'uid': u.uid,
                        'email': (u.email or '').strip(),
                        'created_at': _format_firebase_timestamp(ts),
                        'disabled': getattr(u, 'disabled', False),
                    })
            else:
                while page:
                    for u in page.users:
                        meta = getattr(u, 'user_metadata', None) or getattr(u, 'metadata', None)
                        ts = getattr(meta, 'creation_timestamp', None) if meta else None
                        users.append({
                            'uid': u.uid,
                            'email': (u.email or '').strip(),
                            'created_at': _format_firebase_timestamp(ts),
                            'disabled': getattr(u, 'disabled', False),
                        })
                    page = page.get_next_page() if hasattr(page, 'get_next_page') else None
        except Exception as e:
            users = [{'error': str(e)}]
    return render_template('admin/users.html', users=users)


@app.route('/admin/api/users/disable', methods=['POST'])
@admin_required
def admin_user_disable():
    """Disable a Firebase user by UID."""
    if not _firebase_app:
        return jsonify({'error': 'Firebase not configured'}), 503
    data = request.json or {}
    uid = (data.get('uid') or '').strip()
    if not uid:
        return jsonify({'error': 'uid required'}), 400
    try:
        from firebase_admin import auth as fb_auth
        fb_auth.update_user(uid, disabled=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/admin/api/users/enable', methods=['POST'])
@admin_required
def admin_user_enable():
    """Enable a Firebase user by UID."""
    if not _firebase_app:
        return jsonify({'error': 'Firebase not configured'}), 503
    data = request.json or {}
    uid = (data.get('uid') or '').strip()
    if not uid:
        return jsonify({'error': 'uid required'}), 400
    try:
        from firebase_admin import auth as fb_auth
        fb_auth.update_user(uid, disabled=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/admin/api/users/delete', methods=['POST'])
@admin_required
def admin_user_delete():
    """Delete a Firebase user by UID."""
    if not _firebase_app:
        return jsonify({'error': 'Firebase not configured'}), 503
    data = request.json or {}
    uid = (data.get('uid') or '').strip()
    if not uid:
        return jsonify({'error': 'uid required'}), 400
    try:
        from firebase_admin import auth as fb_auth
        fb_auth.delete_user(uid)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/admin/api/users/password-reset-link', methods=['POST'])
@admin_required
def admin_user_password_reset_link():
    """Generate a password reset link for a user's email. Admin can send the link to the user."""
    if not _firebase_app:
        return jsonify({'error': 'Firebase not configured'}), 503
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email required'}), 400
    try:
        from firebase_admin import auth as fb_auth
        link = fb_auth.generate_password_reset_link(email)
        return jsonify({'success': True, 'link': link})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/admin/subscriptions')
@admin_required
def admin_subscriptions():
    subs = list_all_subscriptions()
    return render_template('admin/subscriptions.html', subscriptions=subs)


@app.route('/admin/api/subscriptions/update', methods=['POST'])
@admin_required
def admin_subscriptions_update():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    plan = (data.get('plan') or '').strip().lower()
    status = (data.get('status') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email required'}), 400
    if plan and plan in ('free', 'starter', 'pro'):
        update_subscription_plan(email, plan)
    if status and status in ('active', 'cancelled', 'past_due'):
        update_subscription_status(email, status)
    return jsonify({'success': True})


@app.route('/admin/campaigns')
@admin_required
def admin_campaigns():
    campaigns = list_all_campaigns()
    # Format for template
    formatted_campaigns = []
    for c in campaigns:
        # Calculate counts if not present
        ad_count = len(c.get('ads', []))
        send_count = c.get('send_count', 0)
        
        formatted_campaigns.append({
            'id': c.get('id'),
            'brand_name': c.get('brand_name'),
            'competitor_name': c.get('competitor_name'),
            'status': c.get('status'),
            'created_at': str(c.get('created_at')),
            'ad_count': ad_count,
            'send_count': send_count,
        })
    return render_template('admin/campaigns.html', campaigns=formatted_campaigns)


@app.route('/admin/usage')
@admin_required
def admin_usage():
    stats = get_usage_stats()
    return render_template('admin/usage.html',
                          sms_total=stats.get('sms_total', 0), 
                          email_total=stats.get('email_total', 0),
                          sms_sent=stats.get('sms_sent', 0), 
                          email_sent=stats.get('email_sent', 0))


@app.route('/admin/pricing')
@admin_required
def admin_pricing():
    pricing = get_pricing()
    return render_template('admin/pricing.html', pricing=pricing)


@app.route('/admin/api/pricing', methods=['POST'])
@admin_required
def admin_pricing_save():
    data = request.json or {}
    set_pricing(data)
    return jsonify({'success': True})


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


# ── SendGrid Single Sender Verification ──────────────────────────────────────

@app.route('/api/sendgrid/verify-sender', methods=['POST'])
def sendgrid_verify_sender():
    """
    Create a SendGrid single sender verification request.
    SendGrid will email the given address a confirmation link.
    """
    import ssl
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
    except Exception:
        pass

    try:
        import sendgrid as sg_module
        from sendgrid import SendGridAPIClient
    except ImportError:
        return jsonify({'success': False, 'error': 'SendGrid library not installed'}), 500

    data = request.json or {}
    email      = (data.get('email') or '').strip().lower()
    name       = (data.get('name') or '').strip()
    reply_to   = (data.get('reply_to') or email).strip().lower()
    nickname   = (data.get('nickname') or name or email).strip()
    address    = (data.get('address') or '123 Main St').strip()
    city       = (data.get('city') or 'New York').strip()
    country    = (data.get('country') or 'US').strip()

    if not email:
        return jsonify({'success': False, 'error': 'Email is required'}), 400

    api_key = os.getenv('SENDGRID_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'SendGrid API key not configured'}), 500

    print(f"[SenderVerify] Requesting single sender verification for: {email}")

    import json as _json

    try:
        client = SendGridAPIClient(api_key=api_key)

        # ── Check if this sender already exists ───────────────────────────
        try:
            existing = client.client.verified_senders.get()
            if existing.status_code == 200:
                body = _json.loads(existing.body)
                for sender in body.get('results', []):
                    if sender.get('from_email', '').lower() == email:
                        verified = sender.get('verified', False)
                        print(f"[SenderVerify] Sender already exists — verified={verified}")
                        return jsonify({
                            'success': True,
                            'already_exists': True,
                            'verified': verified,
                            'message': (
                                'This sender is already verified and ready to use.'
                                if verified else
                                'Verification email already sent. Please check your inbox and click the confirmation link.'
                            )
                        })
        except Exception as check_err:
            print(f"[SenderVerify] Could not check existing senders: {check_err}")

        # ── Build the flat payload SendGrid requires ───────────────────────
        # SendGrid Single Sender API uses flat field names, NOT nested objects.
        payload = {
            "nickname":       nickname,
            "from_email":     email,
            "from_name":      name or nickname,
            "reply_to":       reply_to,
            "reply_to_name":  name or nickname,
            "address":        address,
            "address2":       (data.get('address2') or '').strip(),
            "city":           city,
            "state":          (data.get('state') or '').strip(),
            "zip":            (data.get('zip') or '').strip(),
            "country":        country,
        }

        print(f"[SenderVerify] Payload: {_json.dumps(payload)}")
        response = client.client.verified_senders.post(request_body=payload)
        print(f"[SenderVerify] API response: {response.status_code}")

        if response.status_code in (200, 201):
            return jsonify({
                'success': True,
                'already_exists': False,
                'verified': False,
                'message': (
                    f'Verification email sent to {email}. '
                    'Please check your inbox and click the confirmation link from SendGrid.'
                )
            })

        # Non-2xx but no exception — parse SendGrid error body
        body = {}
        try:
            body = _json.loads(response.body)
        except Exception:
            pass
        errors = body.get('errors', [])
        msg = errors[0].get('message', f'SendGrid returned HTTP {response.status_code}') if errors else str(body)
        print(f"[SenderVerify] Error from SendGrid: {msg}")
        return jsonify({'success': False, 'error': msg}), 400

    except Exception as exc:
        # Extract the real SendGrid error body from the exception when available
        error_detail = str(exc)
        try:
            if hasattr(exc, 'body'):
                sg_body = _json.loads(exc.body)
                errors = sg_body.get('errors', [])
                if errors:
                    error_detail = errors[0].get('message', error_detail)
                    print(f"[SenderVerify] SendGrid body error: {error_detail}")
        except Exception:
            pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_detail}), 500


@app.route('/api/sendgrid/sender-status', methods=['GET'])
def sendgrid_sender_status():
    """
    Check whether a given email address is a verified SendGrid single sender.
    Query param: ?email=user@example.com
    """
    import ssl
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
    except Exception:
        pass

    try:
        from sendgrid import SendGridAPIClient
    except ImportError:
        return jsonify({'success': False, 'error': 'SendGrid library not installed'}), 500

    email = (request.args.get('email') or '').strip().lower()
    if not email:
        return jsonify({'success': False, 'error': 'email query param required'}), 400

    api_key = os.getenv('SENDGRID_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'SendGrid API key not configured'}), 500

    try:
        import json as _json
        client = SendGridAPIClient(api_key=api_key)
        response = client.client.verified_senders.get()

        if response.status_code == 200:
            body = _json.loads(response.body)
            for sender in body.get('results', []):
                if sender.get('from_email', '').lower() == email:
                    return jsonify({
                        'success': True,
                        'found': True,
                        'verified': sender.get('verified', False),
                        'nickname': sender.get('nickname', ''),
                        'from_name': sender.get('from_name', '')
                    })
            return jsonify({'success': True, 'found': False, 'verified': False})
        else:
            return jsonify({'success': False, 'error': f'SendGrid API returned {response.status_code}'}), 400

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────

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
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'Login required'}), 401
        email = (session.get('user_email') or '').strip().lower()
        data = dict(request.json or {})
        data['user_email'] = email
        try:
            from .usage_limits import get_usage, check_can_generate
            usage = get_usage(email)
            max_variations = (usage.get('limits') or {}).get('ad_variations', 3)
            num_variations = min(int(data.get('num_variations') or 3), max(1, max_variations))
            data['num_variations'] = num_variations
            allowed, msg = check_can_generate(email, num_ads=num_variations, new_campaign=True)
            if not allowed:
                return jsonify({'success': False, 'error': msg, 'limit_exceeded': True}), 402
        except Exception as e:
            print(f"[STEP 2] Usage check error: {e}")
        print(f"[STEP 2] Input data: {json.dumps({k: v for k, v in data.items() if k != 'user_email'}, indent=2)}")
        
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
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'Login required'}), 401
        email = (session.get('user_email') or '').strip().lower()
        data = request.json or {}
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
        
        num_sms = len([u for u in sms_users if u.get('phone')])
        num_email = len([u for u in email_users if u.get('email')])
        try:
            from .usage_limits import check_can_send
            allowed, msg = check_can_send(email, num_sms, num_email)
            if not allowed:
                return jsonify({'success': False, 'error': msg, 'limit_exceeded': True}), 402
        except Exception as e:
            print(f"[STEP 4] Usage check error: {e}")
        
        # Get campaign_id from session (stored during generation) or request
        campaign_id = session.get('campaign_id') or data.get('campaign_id')
        
        # Prepare job data
        job_data = {
            'campaign_id': campaign_id,
            'sms_users': sms_users,
            'email_users': email_users,
            'ads': ads,
            'user_email': email,
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


@app.route('/api/auto-marketing', methods=['GET', 'POST'])
def auto_marketing():
    """Get or save auto marketing settings. POST requires Starter/Pro (automation allowed)."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Login required'}), 401
    email = (session.get('user_email') or '').strip().lower()
    try:
        from .auto_marketing import get_settings, save_settings, FREQUENCIES
        from .usage_limits import get_usage
        usage = get_usage(email)
        if request.method == 'GET':
            settings = get_settings(email)
            settings['available'] = bool(usage.get('limits', {}).get('automation', False))
            return jsonify(settings)
        if request.method == 'POST':
            if not usage.get('limits', {}).get('automation', False):
                return jsonify({'error': 'Auto marketing is not available on your plan. Upgrade to Starter or Pro.'}), 403
            data = request.json or {}
            enabled = bool(data.get('enabled', False))
            frequency = (data.get('frequency') or 'weekly').strip().lower()
            if frequency not in FREQUENCIES:
                frequency = 'weekly'
            campaign_params = data.get('campaign_params') or {}
            recipients = data.get('recipients') or []
            save_settings(email, enabled=enabled, frequency=frequency, campaign_params=campaign_params, recipients=recipients)
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    port = int(os.getenv('PORT', 5001))
    print("=" * 60)
    print("AdsCompetitor Web Application")
    print("=" * 60)
    print("\nStarting server...")
    print(f"Open your browser to: http://127.0.0.1:{port}")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    try:
        from .scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print("Scheduler (Auto Marketing):", e)
    app.run(debug=True, host='0.0.0.0', port=port)

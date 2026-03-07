"""
Start the web application on port 5001.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_app'))

# ── Load .env ────────────────────────────────────────────────
env_path = project_root / '.env'
load_dotenv(env_path)

def _mask(val: str, show: int = 8) -> str:
    """Show first `show` chars then '...' so we can confirm a key loaded."""
    if not val:
        return '<NOT SET>'
    return val[:show] + '...' if len(val) > show else val

print()
print("=" * 60)
print("  AdsCompetitor  –  DEBUG STARTUP")
print("=" * 60)
print(f"[STARTUP] .env path       : {env_path}  (exists={env_path.exists()})")
print()
print("[KEYS] API keys loaded:")
print(f"  GEMINI_API_KEY        = {_mask(os.getenv('GEMINI_API_KEY'))}")
print(f"  TWILIO_ACCOUNT_SID    = {_mask(os.getenv('TWILIO_ACCOUNT_SID'))}")
print(f"  TWILIO_AUTH_TOKEN     = {_mask(os.getenv('TWILIO_AUTH_TOKEN'))}")
print(f"  TWILIO_PHONE_NUMBER   = {os.getenv('TWILIO_PHONE_NUMBER', '<NOT SET>')}")
print(f"  SENDGRID_API_KEY      = {_mask(os.getenv('SENDGRID_API_KEY'))}")
print(f"  SENDGRID_FROM_EMAIL   = {os.getenv('SENDGRID_FROM_EMAIL', '<NOT SET>')}")
print()
print("[CONFIG] Notification settings:")
print(f"  NOTIFICATION_ENABLED  = {os.getenv('NOTIFICATION_ENABLED', 'true')}")
print(f"  AI_GEN_MODEL_NAME     = {os.getenv('AI_GEN_MODEL_NAME', 'gemini-1.5-flash')}")
print(f"  AI_GEN_TEMPERATURE    = {os.getenv('AI_GEN_TEMPERATURE', '0.7')}")
print("=" * 60)
print()

# Import and run the app
from web_app.app import app

if __name__ == '__main__':
    port = 5000
    print(f"[STARTUP] Starting server on port {port}...")
    print(f"[STARTUP] Open your browser to: http://localhost:{port}")
    print("[STARTUP] Press Ctrl+C to stop")
    print()
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)

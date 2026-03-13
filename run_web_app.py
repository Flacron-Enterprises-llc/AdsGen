"""
Quick script to run the web application.
"""
import sys
import os
from pathlib import Path

# Add project root to path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

# Import and run the app (do not chdir; reloader re-runs this script from project root)
from web_app.app import app

if __name__ == '__main__':
    import os
    port = int(os.getenv('PORT', 5001))
    try:
        from web_app.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print("Scheduler (Auto Marketing):", e)
    print("=" * 60)
    print("AdsCompetitor Web Application")
    print("=" * 60)
    print("\nStarting server...")
    print(f"Open your browser to: http://localhost:{port}")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    print()
    app.run(debug=True, host='0.0.0.0', port=port)

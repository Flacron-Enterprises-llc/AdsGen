"""
Scheduler for Auto Marketing Mode: runs due campaigns periodically.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
_scheduler = None


def run_auto_marketing_job():
    """Find due auto-marketing users, generate ads and send, then reschedule."""
    try:
        from .auto_marketing import list_due, mark_run
        from .usage_limits import check_can_generate, check_can_send
        due = list_due()
        if not due:
            return
        logger.info("Auto marketing: %d due", len(due))
        for settings in due:
            email = settings.get("email") or settings.get("id")
            if not email:
                continue
            params = settings.get("campaign_params") or {}
            recipients = settings.get("recipients") or []
            sms_users = [r for r in recipients if r.get("phone")]
            email_users = [r for r in recipients if r.get("email")]
            if not sms_users and not email_users:
                logger.warning("Auto marketing %s: no recipients", email)
                mark_run(email)
                continue
            try:
                from .usage_limits import get_usage
                usage = get_usage(email)
                limits = usage.get("limits", {})
            except Exception:
                limits = {}
            if not limits.get("automation", False):
                logger.warning("Auto marketing %s: plan does not allow automation", email)
                mark_run(email)
                continue
            allowed, _ = check_can_generate(email, num_ads=params.get("num_variations", 3), new_campaign=True)
            if not allowed:
                logger.warning("Auto marketing %s: limit exceeded, skipping", email)
                mark_run(email)
                continue
            num_sms = len(sms_users)
            num_email = len(email_users)
            allowed, _ = check_can_send(email, num_sms, num_email)
            if not allowed:
                logger.warning("Auto marketing %s: send limit exceeded", email)
                mark_run(email)
                continue
            try:
                from jobs.job_handlers import generate_ads_job, send_notifications_job
                data = dict(params)
                data["user_email"] = email
                result = generate_ads_job(data)
                if not result.get("success"):
                    logger.warning("Auto marketing %s: generate failed %s", email, result.get("error"))
                    mark_run(email)
                    continue
                ads = result.get("ads", [])
                campaign_id = result.get("campaign_id")
                job_data = {
                    "campaign_id": campaign_id,
                    "sms_users": sms_users,
                    "email_users": email_users,
                    "ads": ads,
                    "user_email": email,
                }
                send_result = send_notifications_job(job_data)
                if send_result.get("success"):
                    logger.info("Auto marketing %s: sent successfully", email)
                else:
                    logger.warning("Auto marketing %s: send failed %s", email, send_result.get("error"))
            except Exception as e:
                logger.exception("Auto marketing %s: %s", email, e)
            mark_run(email)
    except Exception as e:
        logger.exception("Auto marketing job error: %s", e)


def start_scheduler():
    """Start APScheduler with auto_marketing job every hour."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(run_auto_marketing_job, "interval", hours=1, id="auto_marketing")
        _scheduler.start()
        logger.info("Scheduler started (auto marketing every 1 hour)")
    except ImportError:
        logger.warning("APScheduler not installed. pip install apscheduler for Auto Marketing Mode.")
    except Exception as e:
        logger.exception("Scheduler start failed: %s", e)


def stop_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown()
        except Exception:
            pass
        _scheduler = None

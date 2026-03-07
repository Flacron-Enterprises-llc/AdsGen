"""
Configuration utilities for the Notification Layer.
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env file from project root (two levels up from this file)
    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # dotenv not installed, skip loading .env file
    pass

from .exceptions import ConfigurationError


def _mask(val: Optional[str], show: int = 8) -> str:
    if not val:
        return '<NOT SET>'
    return val[:show] + '...' if len(val) > show else val


class NotificationConfig:
    """Configuration manager for notification services."""

    def __init__(self):
        """Initialize configuration from environment variables."""
        self.twilio_config = self._load_twilio_config()
        self.sendgrid_config = self._load_sendgrid_config()
        self.general_config = self._load_general_config()

        print("\n[NotificationConfig] Credentials loaded:")
        print(f"  Twilio  SID    = {_mask(self.twilio_config.get('account_sid'))}")
        print(f"  Twilio  Token  = {_mask(self.twilio_config.get('auth_token'))}")
        print(f"  Twilio  Phone  = {self.twilio_config.get('phone_number', '<NOT SET>')}")
        print(f"  Twilio  enabled= {self.twilio_config.get('enabled')}")
        print(f"  SendGrid Key   = {_mask(self.sendgrid_config.get('api_key'))}")
        print(f"  SendGrid Email = {self.sendgrid_config.get('from_email', '<NOT SET>')}")
        print(f"  SendGrid enabled={self.sendgrid_config.get('enabled')}")
    
    @staticmethod
    def _is_placeholder(value: Optional[str]) -> bool:
        """Return True if value looks like an unfilled placeholder."""
        if not value:
            return True
        lowered = value.lower().strip()
        return (
            lowered.startswith("your_")
            or lowered.endswith("_here")
            or lowered in ("", "none", "null", "changeme", "placeholder")
        )

    def _load_twilio_config(self) -> Dict[str, Any]:
        """Load Twilio configuration from environment variables."""
        config = {
            "account_sid": os.getenv("TWILIO_ACCOUNT_SID"),
            "auth_token": os.getenv("TWILIO_AUTH_TOKEN"),
            "phone_number": os.getenv("TWILIO_PHONE_NUMBER"),
            "enabled": os.getenv("TWILIO_ENABLED", "true").lower() in ("true", "1", "yes")
        }

        if config["enabled"]:
            required_fields = ["account_sid", "auth_token", "phone_number"]
            if any(self._is_placeholder(config[f]) for f in required_fields):
                config["enabled"] = False

        return config

    def _load_sendgrid_config(self) -> Dict[str, Any]:
        """Load SendGrid configuration from environment variables."""
        config = {
            "api_key": os.getenv("SENDGRID_API_KEY"),
            "from_email": os.getenv("SENDGRID_FROM_EMAIL"),
            "from_name": os.getenv("SENDGRID_FROM_NAME", "AdsCompetitor"),
            "enabled": os.getenv("SENDGRID_ENABLED", "true").lower() in ("true", "1", "yes")
        }

        if config["enabled"]:
            required_fields = ["api_key", "from_email"]
            if any(self._is_placeholder(config[f]) for f in required_fields):
                config["enabled"] = False

        return config
    
    def _load_general_config(self) -> Dict[str, Any]:
        """Load general notification configuration."""
        return {
            "enabled": os.getenv("NOTIFICATION_ENABLED", "true").lower() in ("true", "1", "yes"),
            "retry_attempts": int(os.getenv("NOTIFICATION_RETRY_ATTEMPTS", "3")),
            "timeout": float(os.getenv("NOTIFICATION_TIMEOUT", "30.0")),
            "batch_size": int(os.getenv("NOTIFICATION_BATCH_SIZE", "100")),
            "rate_limit_per_minute": int(os.getenv("NOTIFICATION_RATE_LIMIT", "60")),
            "log_level": os.getenv("NOTIFICATION_LOG_LEVEL", "INFO")
        }
    
    def get_twilio_config(self) -> Dict[str, Any]:
        """Get Twilio configuration."""
        return self.twilio_config.copy()
    
    def get_sendgrid_config(self) -> Dict[str, Any]:
        """Get SendGrid configuration."""
        return self.sendgrid_config.copy()
    
    def get_general_config(self) -> Dict[str, Any]:
        """Get general configuration."""
        return self.general_config.copy()
    
    def is_twilio_enabled(self) -> bool:
        """Check if Twilio is enabled."""
        return self.twilio_config["enabled"] and self.general_config["enabled"]
    
    def is_sendgrid_enabled(self) -> bool:
        """Check if SendGrid is enabled."""
        return self.sendgrid_config["enabled"] and self.general_config["enabled"]
    
    def validate_config(self) -> None:
        """Validate the entire configuration."""
        if not self.general_config["enabled"]:
            return  # If notifications are disabled, no need to validate providers
        
        # Don't require providers to be enabled - allow app to work without notification setup
        # This allows ad generation to work even if notifications aren't configured
        # Providers will be checked when actually trying to send notifications
        
        # Validate retry attempts
        if self.general_config["retry_attempts"] < 0:
            raise ConfigurationError("Retry attempts must be non-negative")
        
        # Validate timeout
        if self.general_config["timeout"] <= 0:
            raise ConfigurationError("Timeout must be positive")
        
        # Validate batch size
        if self.general_config["batch_size"] <= 0:
            raise ConfigurationError("Batch size must be positive")
        
        # Validate rate limit
        if self.general_config["rate_limit_per_minute"] <= 0:
            raise ConfigurationError("Rate limit must be positive")

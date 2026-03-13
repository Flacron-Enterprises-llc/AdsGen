"""
Twilio SMS provider for sending SMS notifications.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioException
except ImportError:
    Client = None
    TwilioException = Exception

from .base_provider import BaseNotificationProvider
from ..models.message_models import NotificationResult, SMSMessage
from ..models.notification_types import NotificationType, NotificationStatus
from ..exceptions import SMSDeliveryError, AuthenticationError, RateLimitError


class TwilioSMSProvider(BaseNotificationProvider):
    """Twilio SMS provider implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Twilio SMS provider.
        
        Args:
            config: Twilio configuration dictionary
        """
        super().__init__(config)
        self.client = None
        self.logger = logging.getLogger(__name__)
        self._initialize_client()
    
    def _validate_config(self) -> None:
        """Validate Twilio configuration."""
        required_fields = ["account_sid", "auth_token", "phone_number"]
        for field in required_fields:
            if not self.config.get(field):
                raise ValueError(f"Missing required Twilio config field: {field}")
    
    def _initialize_client(self) -> None:
        """Initialize Twilio client."""
        if Client is None:
            raise ImportError(
                "Twilio library not installed. Install with: pip install twilio>=8.0.0"
            )

        sid = self.config.get("account_sid", "")
        print(f"[TwilioProvider] Initialising client — SID={sid[:8]}...  Phone={self.config.get('phone_number')}")
        self.client = Client(
            self.config["account_sid"],
            self.config["auth_token"]
        )
        print("[TwilioProvider] ✓ Client created (credentials accepted by SDK)")
    
    def send_notification(self, message_data: Dict[str, Any]) -> NotificationResult:
        """
        Send SMS notification via Twilio.
        
        Args:
            message_data: SMS message data
            
        Returns:
            NotificationResult with delivery status
        """
        try:
            # Validate message data
            sms_message = SMSMessage(**message_data)
            sms_message.validate()
            
            # Prepare Twilio message parameters
            message_params = {
                "body": sms_message.message,
                "from_": self.config["phone_number"],
                "to": sms_message.to_phone
            }
            
            # Add media URLs if provided
            if sms_message.media_urls:
                message_params["media_url"] = sms_message.media_urls
            
            print(f"[TwilioProvider] Sending SMS to {sms_message.to_phone} from {self.config['phone_number']}")
            self.logger.info(f"Sending SMS to {sms_message.to_phone}")
            message = self.client.messages.create(**message_params)
            
            # Create success result
            result = NotificationResult(
                success=True,
                message_id=message.sid,
                status=NotificationStatus.SENT,
                delivery_time=datetime.now(),
                provider_response={
                    "twilio_sid": message.sid,
                    "status": message.status,
                    "price": message.price,
                    "price_unit": message.price_unit
                }
            )
            
            print(f"[TwilioProvider] ✓ SMS sent — SID={message.sid}  status={message.status}")
            self.logger.info(f"SMS sent successfully. SID: {message.sid}")
            return result
            
        except TwilioException as e:
            error_message = str(e)
            self.logger.error(f"Twilio SMS delivery failed: {error_message}")
            
            # Determine error type and status
            if "Authentication" in error_message:
                raise AuthenticationError(f"Twilio authentication failed: {error_message}")
            elif "rate limit" in error_message.lower():
                raise RateLimitError(f"Twilio rate limit exceeded: {error_message}")
            else:
                return NotificationResult(
                    success=False,
                    status=NotificationStatus.FAILED,
                    error_message=error_message,
                    provider_response={"twilio_error": error_message}
                )
        
        except Exception as e:
            error_message = str(e)
            self.logger.error(f"Unexpected error sending SMS: {error_message}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=error_message
            )
    
    def get_message_status(self, message_id: str) -> NotificationStatus:
        """
        Get the status of a sent message.
        
        Args:
            message_id: Twilio message SID
            
        Returns:
            Current message status
        """
        try:
            message = self.client.messages(message_id).fetch()
            
            # Map Twilio status to our status enum
            status_mapping = {
                "queued": NotificationStatus.PENDING,
                "sending": NotificationStatus.PENDING,
                "sent": NotificationStatus.SENT,
                "delivered": NotificationStatus.DELIVERED,
                "undelivered": NotificationStatus.FAILED,
                "failed": NotificationStatus.FAILED
            }
            
            return status_mapping.get(message.status, NotificationStatus.FAILED)
            
        except TwilioException as e:
            self.logger.error(f"Failed to get message status: {e}")
            return NotificationStatus.FAILED
    
    def get_provider_name(self) -> str:
        """Get the name of the provider."""
        return "Twilio SMS"
    
    def get_supported_type(self) -> NotificationType:
        """Get the notification type this provider supports."""
        return NotificationType.SMS
    
    def get_balance(self) -> Optional[float]:
        """
        Get account balance.
        
        Returns:
            Account balance in USD, or None if unavailable
        """
        try:
            account = self.client.api.accounts(self.config["account_sid"]).fetch()
            # Handle BalanceList object - get the first balance entry
            balance_obj = account.balance
            if hasattr(balance_obj, 'balance'):
                balance = float(balance_obj.balance)
            elif isinstance(balance_obj, (int, float, str)):
                balance = float(balance_obj)
            else:
                # If it's a list-like object, try to get first item
                try:
                    balance = float(balance_obj[0].balance if hasattr(balance_obj[0], 'balance') else balance_obj[0])
                except:
                    return None
            return balance
        except (TwilioException, ValueError, TypeError, AttributeError):
            return None

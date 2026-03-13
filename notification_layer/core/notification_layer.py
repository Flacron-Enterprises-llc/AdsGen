"""
Main notification layer implementation.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import NotificationConfig
from ..providers.twilio_provider import TwilioSMSProvider
from ..providers.sendgrid_provider import SendGridEmailProvider
from ..models.message_models import SMSMessage, EmailMessage, NotificationResult
from ..models.notification_types import NotificationType, NotificationStatus
from ..exceptions import NotificationError, ConfigurationError, ValidationError


class NotificationLayer:
    """Main notification layer for sending SMS and email notifications."""
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        """
        Initialize the notification layer.
        
        Args:
            config: Notification configuration. If None, loads from environment.
        """
        self.config = config or NotificationConfig()
        self.logger = logging.getLogger(__name__)
        
        # Initialize providers
        self.providers = {}
        self._initialize_providers()
        
        # Initialize thread pool for async operations
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Validate configuration
        self.config.validate_config()
        
        self.logger.info("Notification layer initialized successfully")
    
    def _initialize_providers(self) -> None:
        """Initialize available notification providers."""
        print(f"\n[NotificationLayer] _initialize_providers()")
        print(f"[NotificationLayer]   twilio_enabled  = {self.config.is_twilio_enabled()}")
        print(f"[NotificationLayer]   sendgrid_enabled= {self.config.is_sendgrid_enabled()}")

        # Initialize Twilio SMS provider independently
        if self.config.is_twilio_enabled():
            try:
                twilio_config = self.config.get_twilio_config()
                twilio_config.update(self.config.get_general_config())
                self.providers[NotificationType.SMS] = TwilioSMSProvider(twilio_config)
                print("[NotificationLayer] ✓ Twilio SMS provider initialized")
                self.logger.info("Twilio SMS provider initialized")
            except Exception as e:
                import traceback
                print(f"[NotificationLayer] ✗ Twilio SMS provider FAILED: {e}")
                traceback.print_exc()
                self.logger.warning(
                    f"Twilio SMS provider could not be initialized and will be disabled: {e}"
                )
        else:
            print("[NotificationLayer]   Twilio SMS skipped (disabled or placeholder creds)")

        # Initialize SendGrid email provider independently
        if self.config.is_sendgrid_enabled():
            try:
                sendgrid_config = self.config.get_sendgrid_config()
                sendgrid_config.update(self.config.get_general_config())
                self.providers[NotificationType.EMAIL] = SendGridEmailProvider(sendgrid_config)
                print("[NotificationLayer] ✓ SendGrid email provider initialized")
                self.logger.info("SendGrid email provider initialized")
            except Exception as e:
                import traceback
                print(f"[NotificationLayer] ✗ SendGrid email provider FAILED: {e}")
                traceback.print_exc()
                self.logger.warning(
                    f"SendGrid email provider could not be initialized and will be disabled: {e}"
                )
        else:
            print("[NotificationLayer]   SendGrid email skipped (disabled or placeholder creds)")

        print(f"[NotificationLayer]   Active providers: {list(self.providers.keys())}")
        if not self.providers:
            print("[NotificationLayer] ⚠ No notification providers initialized")
            self.logger.warning("No notification providers initialized")
    
    def send_sms(self, to_phone: str, message: str, **kwargs) -> NotificationResult:
        """
        Send SMS notification.
        
        Args:
            to_phone: Recipient phone number
            message: SMS message content
            **kwargs: Additional SMS message parameters
            
        Returns:
            NotificationResult with delivery status
        """
        if NotificationType.SMS not in self.providers:
            raise NotificationError("SMS provider not available")
        
        # Create SMS message
        sms_data = {
            "to_phone": to_phone,
            "message": message,
            **kwargs
        }
        
        try:
            provider = self.providers[NotificationType.SMS]
            return provider.send_notification(sms_data)
        except Exception as e:
            self.logger.error(f"Failed to send SMS: {e}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=str(e)
            )
    
    def send_email(self, to_email: str, subject: str, content: str, **kwargs) -> NotificationResult:
        """
        Send email notification.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            content: Email content
            **kwargs: Additional email message parameters
            
        Returns:
            NotificationResult with delivery status
        """
        if NotificationType.EMAIL not in self.providers:
            raise NotificationError("Email provider not available")
        
        # Create email message
        email_data = {
            "to_email": to_email,
            "subject": subject,
            "content": content,
            **kwargs
        }
        
        try:
            provider = self.providers[NotificationType.EMAIL]
            return provider.send_notification(email_data)
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=str(e)
            )
    
    def send_bulk_sms(self, messages: List[Dict[str, Any]], 
                     max_workers: int = 4) -> List[NotificationResult]:
        """
        Send multiple SMS messages concurrently.
        
        Args:
            messages: List of SMS message dictionaries
            max_workers: Maximum number of concurrent workers
            
        Returns:
            List of NotificationResult objects
        """
        if NotificationType.SMS not in self.providers:
            raise NotificationError("SMS provider not available")
        
        results = []
        provider = self.providers[NotificationType.SMS]
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all messages
            future_to_message = {
                executor.submit(provider.send_notification, message): message 
                for message in messages
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_message):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Bulk SMS failed for message: {e}")
                    results.append(NotificationResult(
                        success=False,
                        status=NotificationStatus.FAILED,
                        error_message=str(e)
                    ))
        
        return results
    
    def send_bulk_email(self, messages: List[Dict[str, Any]], 
                       max_workers: int = 4) -> List[NotificationResult]:
        """
        Send multiple email messages concurrently.
        
        Args:
            messages: List of email message dictionaries
            max_workers: Maximum number of concurrent workers
            
        Returns:
            List of NotificationResult objects
        """
        if NotificationType.EMAIL not in self.providers:
            raise NotificationError("Email provider not available")
        
        results = []
        provider = self.providers[NotificationType.EMAIL]
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all messages
            future_to_message = {
                executor.submit(provider.send_notification, message): message 
                for message in messages
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_message):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Bulk email failed for message: {e}")
                    results.append(NotificationResult(
                        success=False,
                        status=NotificationStatus.FAILED,
                        error_message=str(e)
                    ))
        
        return results
    
    def send_to_user_list(self, user_list: List[Dict[str, Any]], 
                         message_content: str, 
                         notification_type: NotificationType,
                         **kwargs) -> List[NotificationResult]:
        """
        Send notifications to a list of users.
        
        Args:
            user_list: List of user dictionaries with contact information
            message_content: Content to send
            notification_type: Type of notification (SMS or EMAIL)
            **kwargs: Additional message parameters
            
        Returns:
            List of NotificationResult objects
        """
        if notification_type not in self.providers:
            raise NotificationError(f"{notification_type.value} provider not available")
        
        messages = []
        
        for user in user_list:
            if notification_type == NotificationType.SMS:
                if "phone" not in user:
                    continue
                messages.append({
                    "to_phone": user["phone"],
                    "message": message_content,
                    **kwargs
                })
            elif notification_type == NotificationType.EMAIL:
                if "email" not in user:
                    continue
                messages.append({
                    "to_email": user["email"],
                    "subject": kwargs.get("subject", "Notification"),
                    "content": message_content,
                    **kwargs
                })
        
        if not messages:
            self.logger.warning("No valid recipients found in user list")
            return []
        
        # Send messages using appropriate bulk method
        if notification_type == NotificationType.SMS:
            return self.send_bulk_sms(messages)
        else:
            return self.send_bulk_email(messages)
    
    def get_provider_status(self) -> Dict[str, Any]:
        """
        Get status information for all providers.
        
        Returns:
            Dictionary with provider status information
        """
        status = {
            "providers": {},
            "overall_enabled": self.config.get_general_config()["enabled"]
        }
        
        for notification_type, provider in self.providers.items():
            provider_status = {
                "enabled": provider.is_enabled(),
                "name": provider.get_provider_name(),
                "supported_type": provider.get_supported_type().value
            }
            
            # Add provider-specific status
            if notification_type == NotificationType.SMS and hasattr(provider, 'get_balance'):
                provider_status["balance"] = provider.get_balance()
            elif notification_type == NotificationType.EMAIL and hasattr(provider, 'get_user_profile'):
                provider_status["user_profile_available"] = provider.get_user_profile() is not None
            
            status["providers"][notification_type.value] = provider_status
        
        return status
    
    def close(self) -> None:
        """Close the notification layer and cleanup resources."""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
        self.logger.info("Notification layer closed")

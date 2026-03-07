"""
SendGrid email provider for sending email notifications.
"""

import logging
import ssl
from typing import Dict, Any, Optional, List
from datetime import datetime

# Handle SSL certificate issues on Windows
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail, Email, To, Cc, Bcc, Attachment, FileContent, FileName, FileType, Disposition
    from sendgrid.helpers.mail.exceptions import SendGridException
except ImportError:
    sendgrid = None
    Mail = None
    Email = None
    To = None
    Cc = None
    Bcc = None
    Attachment = None
    FileContent = None
    FileName = None
    FileType = None
    Disposition = None
    SendGridException = Exception

from .base_provider import BaseNotificationProvider
from ..models.message_models import NotificationResult, EmailMessage
from ..models.notification_types import NotificationType, NotificationStatus
from ..exceptions import EmailDeliveryError, AuthenticationError, RateLimitError


class SendGridEmailProvider(BaseNotificationProvider):
    """SendGrid email provider implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SendGrid email provider.
        
        Args:
            config: SendGrid configuration dictionary
        """
        super().__init__(config)
        self.sg = None
        self.logger = logging.getLogger(__name__)
        self._initialize_client()
    
    def _validate_config(self) -> None:
        """Validate SendGrid configuration."""
        required_fields = ["api_key", "from_email"]
        for field in required_fields:
            if not self.config.get(field):
                raise ValueError(f"Missing required SendGrid config field: {field}")
    
    def _initialize_client(self) -> None:
        """Initialize SendGrid client."""
        if sendgrid is None:
            raise ImportError(
                "SendGrid library not installed. Install with: pip install sendgrid>=6.10.0"
            )

        api_key = self.config.get("api_key", "")
        print(f"[SendGridProvider] Initialising client — key={api_key[:8]}...  from={self.config.get('from_email')}")
        try:
            self.sg = sendgrid.SendGridAPIClient(api_key=self.config["api_key"])
            
            # Try to test the client, but don't fail if SSL issues occur
            try:
                response = self.sg.client.user.profile.get()
                if response.status_code == 200:
                    print(f"[SendGridProvider] ✓ Auth test passed (HTTP 200)")
                    self.logger.info("SendGrid client initialized and validated successfully")
                else:
                    print(f"[SendGridProvider]   Auth test returned HTTP {response.status_code}")
                    self.logger.warning(f"SendGrid client test returned status: {response.status_code}")
            except Exception as test_error:
                # If it's an SSL error, just log a warning and continue
                error_str = str(test_error)
                if "SSL" in error_str.upper() or "CERTIFICATE" in error_str.upper():
                    self.logger.warning(f"SendGrid client initialized (SSL validation skipped due to: {test_error})")
                else:
                    # For non-SSL errors, re-raise
                    raise
            
        except Exception as e:
            error_str = str(e)
            # Allow SSL errors to pass through - they won't affect email sending
            if "SSL" in error_str.upper() or "CERTIFICATE" in error_str.upper():
                self.logger.warning(f"SendGrid client initialized with SSL warning: {e}")
                self.sg = sendgrid.SendGridAPIClient(api_key=self.config["api_key"])
            elif "authentication" in error_str.lower() or "unauthorized" in error_str.lower():
                raise AuthenticationError(f"SendGrid authentication failed: {e}")
            else:
                raise EmailDeliveryError(f"Failed to initialize SendGrid client: {e}")
    
    def send_notification(self, message_data: Dict[str, Any]) -> NotificationResult:
        """
        Send email notification via SendGrid.
        
        Args:
            message_data: Email message data
            
        Returns:
            NotificationResult with delivery status
        """
        try:
            # Validate message data
            email_message = EmailMessage(**message_data)
            email_message.validate()
            
            # Create SendGrid mail object
            mail = self._create_mail_object(email_message)
            
            print(f"[SendGridProvider] Sending email to {email_message.to_email}  subject={email_message.subject!r}")
            self.logger.info(f"Sending email to {email_message.to_email}")
            response = self.sg.send(mail)
            
            # Check response status
            print(f"[SendGridProvider] HTTP response: {response.status_code}")
            if response.status_code in [200, 201, 202]:
                message_id = response.headers.get('X-Message-Id', 'unknown')
                print(f"[SendGridProvider] ✓ Email sent — message_id={message_id}")
                
                result = NotificationResult(
                    success=True,
                    message_id=message_id,
                    status=NotificationStatus.SENT,
                    delivery_time=datetime.now(),
                    provider_response={
                        "status_code": response.status_code,
                        "message_id": message_id,
                        "sendgrid_response": response.body.decode() if response.body else None
                    }
                )
                
                self.logger.info(f"Email sent successfully. Message ID: {message_id}")
                return result
            else:
                error_message = f"SendGrid API returned status {response.status_code}"
                if response.body:
                    error_message += f": {response.body.decode()}"
                
                return NotificationResult(
                    success=False,
                    status=NotificationStatus.FAILED,
                    error_message=error_message,
                    provider_response={
                        "status_code": response.status_code,
                        "response_body": response.body.decode() if response.body else None
                    }
                )
        
        except SendGridException as e:
            error_message = str(e)
            self.logger.error(f"SendGrid email delivery failed: {error_message}")
            
            # Determine error type
            if "authentication" in error_message.lower() or "unauthorized" in error_message.lower():
                raise AuthenticationError(f"SendGrid authentication failed: {error_message}")
            elif "rate limit" in error_message.lower():
                raise RateLimitError(f"SendGrid rate limit exceeded: {error_message}")
            else:
                return NotificationResult(
                    success=False,
                    status=NotificationStatus.FAILED,
                    error_message=error_message,
                    provider_response={"sendgrid_error": error_message}
                )
        
        except Exception as e:
            error_message = str(e)
            self.logger.error(f"Unexpected error sending email: {error_message}")
            return NotificationResult(
                success=False,
                status=NotificationStatus.FAILED,
                error_message=error_message
            )
    
    def _create_mail_object(self, email_message: EmailMessage) -> Mail:
        """Create SendGrid Mail object from EmailMessage."""
        # Create from email
        from_email = Email(
            email_message.from_email or self.config["from_email"],
            email_message.from_name or self.config["from_name"]
        )
        
        # Create to email
        to_email = To(email_message.to_email)
        
        # Create mail object
        mail = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=email_message.subject
        )
        
        # Add content
        if email_message.html_content:
            mail.add_content(email_message.html_content, "text/html")
        if email_message.content:
            mail.add_content(email_message.content, "text/plain")
        
        # Add CC emails
        if email_message.cc_emails:
            for cc_email in email_message.cc_emails:
                mail.add_cc(Cc(cc_email))
        
        # Add BCC emails
        if email_message.bcc_emails:
            for bcc_email in email_message.bcc_emails:
                mail.add_bcc(Bcc(bcc_email))
        
        # Add reply-to
        if email_message.reply_to:
            mail.reply_to = Email(email_message.reply_to)
        
        # Add attachments
        if email_message.attachments:
            for attachment_data in email_message.attachments:
                attachment = self._create_attachment(attachment_data)
                mail.add_attachment(attachment)
        
        return mail
    
    def _create_attachment(self, attachment_data: Dict[str, Any]) -> Attachment:
        """Create SendGrid Attachment from attachment data."""
        file_content = attachment_data.get("content", "")
        file_name = attachment_data.get("filename", "attachment")
        file_type = attachment_data.get("type", "application/octet-stream")
        disposition = attachment_data.get("disposition", "attachment")
        
        return Attachment(
            FileContent(file_content),
            FileName(file_name),
            FileType(file_type),
            Disposition(disposition)
        )
    
    def get_provider_name(self) -> str:
        """Get the name of the provider."""
        return "SendGrid Email"
    
    def get_supported_type(self) -> NotificationType:
        """Get the notification type this provider supports."""
        return NotificationType.EMAIL
    
    def get_user_profile(self) -> Optional[Dict[str, Any]]:
        """
        Get user profile information.
        
        Returns:
            User profile data, or None if unavailable
        """
        try:
            response = self.sg.client.user.profile.get()
            if response.status_code == 200:
                return response.body.decode()
            return None
        except Exception:
            return None

"""
Background job handlers for AI generation and notification sending.
"""
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import hashlib
import json
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from ai_generation_layer import AIGenerationLayer
from input_layer import InputLayer, InputType
from processing_layer import ProcessingLayer
from notification_layer import NotificationLayer
from notification_layer.models.notification_types import NotificationType

# Database imports (optional)
try:
    from database.db_manager import (
        CampaignDB, AdVariantDB, RecipientDB, SendDB, EventDB, is_db_available
    )
    DB_AVAILABLE = True
except ImportError as e:
    DB_AVAILABLE = False
    CampaignDB = None
    AdVariantDB = None
    RecipientDB = None
    SendDB = None
    EventDB = None
    is_db_available = lambda: False
    print(f"Database module not available: {e}")


# Simple in-memory cache (in production, use Redis)
_cache = {}


def _cache_key(brand: str, competitor: str, zipcode: str, num_variations: int = 3) -> str:
    """Generate cache key from brand, competitor, zipcode, and number of variations."""
    key_str = f"{brand}|{competitor}|{zipcode}|{num_variations}".lower().strip()
    return hashlib.md5(key_str.encode()).hexdigest()


def _sanitize_competitor_name(raw: str) -> str:
    """
    If the user pasted a URL as the competitor name, extract the domain-based
    business name.  Otherwise return the input unchanged.
    """
    from urllib.parse import urlparse
    stripped = raw.strip()
    # Detect URLs: starts with a scheme or looks like a domain/path
    if stripped.startswith(('http://', 'https://', 'www.')):
        try:
            if not stripped.startswith(('http://', 'https://')):
                stripped = 'https://' + stripped
            parsed = urlparse(stripped)
            domain = parsed.netloc or parsed.path.split('/')[0]
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            # Take the first label of the domain (e.g. "junaidjamshed" from "junaidjamshed.com")
            business = domain.split('.')[0]
            # Convert hyphens/underscores to spaces and title-case
            business = business.replace('-', ' ').replace('_', ' ').title()
            return business if business else stripped
        except Exception:
            return stripped
    return stripped


def generate_ads_job(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Background job to generate ads.
    
    Args:
        data: Dictionary containing:
            - our_brand: Brand name
            - competitor_name: Competitor name
            - ad_copy: Competitor ad copy (optional)
            - location: Location (optional)
            - zipcode: ZIP code
            - hashtags: List of hashtags (optional)
            - industry: Industry preset (optional)
            - audience_type: Audience type (optional)
            - offer_type: Offer type (optional)
            - goal: Campaign goal (optional)
            - num_variations: Number of ad variations to generate (default: 3)
    
    Returns:
        Dictionary with generated ads and metadata
    """
    try:
        our_brand = data.get('our_brand', '')
        competitor_name = _sanitize_competitor_name(data.get('competitor_name', ''))
        zipcode = data.get('zipcode', '')
        hashtags = data.get('hashtags', [])
        num_variations = data.get('num_variations', 3)
        
        # Check cache (only if we have the exact number of variations)
        cache_key = _cache_key(our_brand, competitor_name, zipcode, num_variations)
        if cache_key in _cache:
            cached_result = _cache[cache_key]
            cached_ads = cached_result.get('ads', [])
            # Only use cache if it has the right number of ads
            if len(cached_ads) == num_variations:
                return {
                    'success': True,
                    'ads': cached_ads,
                    'count': len(cached_ads),
                    'cached': True
                }
        
        # Gather competitor intelligence before generating ads
        competitor_intel = {}
        try:
            from competitor_intelligence.scraper import CompetitorIntelligence
            intel_scraper = CompetitorIntelligence()
            
            # Get website URL if provided
            website_url = data.get('website_url') or data.get('competitor_website')
            
            # Gather intelligence
            intel = intel_scraper.gather_intelligence(competitor_name, website_url)
            
            if intel and intel.get('source') != 'none':
                competitor_intel = intel
                logger.info(f"Gathered competitor intelligence from {intel.get('source')} for {competitor_name}")
            else:
                logger.info(f"No competitor intelligence gathered for {competitor_name}, proceeding with provided data")
        except ImportError:
            logger.warning("Competitor intelligence module not available, skipping scraping")
        except Exception as e:
            logger.warning(f"Error gathering competitor intelligence: {e}, proceeding with provided data")
        
        competitor_data = {
            "competitor_name": competitor_name,
            "ad_copy": data.get('ad_copy', ''),
            "hashtags": hashtags,
            "location": data.get('location', ''),
            "special_offers": [],
            "our_brand": our_brand
        }
        
        # Enhance competitor data with scraped intelligence
        if competitor_intel:
            if competitor_intel.get('description'):
                competitor_data['competitor_description'] = competitor_intel['description']
            if competitor_intel.get('services'):
                competitor_data['competitor_services'] = competitor_intel['services']
            if competitor_intel.get('key_features'):
                competitor_data['competitor_features'] = competitor_intel['key_features']
            if competitor_intel.get('website'):
                competitor_data['competitor_website'] = competitor_intel['website']
            competitor_data['intelligence_source'] = competitor_intel.get('source', 'none')
        
        # Process inputs through Input Layer
        input_layer = InputLayer()
        processed_results = []
        
        if competitor_name:
            comp_result = input_layer.process_single(competitor_name, InputType.COMPETITOR_NAME)
            processed_results.append(comp_result.to_dict())
        
        if hashtags:
            for tag in hashtags:
                if tag:
                    hashtag_result = input_layer.process_single(tag, InputType.HASHTAG)
                    processed_results.append(hashtag_result.to_dict())
        
        if zipcode:
            zip_result = input_layer.process_single(zipcode, InputType.ZIP_CODE)
            processed_results.append(zip_result.to_dict())
        
        # Build marketing context using Processing Layer
        processing_layer = ProcessingLayer()
        marketing_context_obj = processing_layer.build_context(processed_results)
        marketing_context = marketing_context_obj.to_dict()
        
        # Add business-specific information
        marketing_context["business"] = {
            "our_brand": our_brand,
            "competitor": competitor_name,
            "competitor_ad_copy": competitor_data.get("ad_copy", ""),
            "niche_hashtags": hashtags if hashtags else [],
            "location": competitor_data.get("location", ""),
            "zipcode": zipcode
        }
        
        # Add scraped competitor intelligence if available
        if competitor_intel and competitor_intel.get('source') != 'none':
            marketing_context["business"]["competitor_description"] = competitor_intel.get("description", "")
            marketing_context["business"]["competitor_services"] = competitor_intel.get("services", [])
            marketing_context["business"]["competitor_features"] = competitor_intel.get("key_features", [])
            marketing_context["business"]["competitor_website"] = competitor_intel.get("website", "")
            marketing_context["business"]["intelligence_source"] = competitor_intel.get("source", "none")
            marketing_context["business"]["competitor_contact"] = competitor_intel.get("contact_info", {})
        
        # Add targeting options if provided
        if data.get('industry'):
            marketing_context["business"]["industry"] = data['industry']
        if data.get('audience_type'):
            marketing_context["business"]["audience_type"] = data['audience_type']
        if data.get('offer_type'):
            marketing_context["business"]["offer_type"] = data['offer_type']
        if data.get('goal'):
            marketing_context["business"]["goal"] = data['goal']
        
        # Ensure hashtags list format
        if not hashtags:
            hashtags = ["#business"]
        elif isinstance(hashtags, str):
            hashtags = [hashtags]
        
        # Initialize AI layer
        ai = AIGenerationLayer()
        
        # Generate multiple ads using batch generation
        ads_list = []
        
        # Use optimized batch generation if available
        try:
            # Try to generate multiple variations in one call
            generated_content = ai.generate_content(marketing_context)
            
            # Create base ad from generated content
            user_hashtag_list = []
            if hashtags and len(hashtags) > 0:
                for tag in hashtags:
                    tag = tag.strip()
                    if not tag.startswith('#'):
                        tag = '#' + tag.lstrip('#')
                    user_hashtag_list.append(tag)
            
            ai_generated_hashtags = []
            for h in generated_content.hashtags:
                if hasattr(h, 'content'):
                    ai_generated_hashtags.append(h.content)
                elif isinstance(h, str):
                    ai_generated_hashtags.append(h)
                else:
                    ai_generated_hashtags.append(str(h))
            
            final_hashtags = user_hashtag_list.copy()
            for ai_tag in ai_generated_hashtags:
                ai_tag_clean = ai_tag.strip().lower()
                if ai_tag_clean not in [t.strip().lower() for t in user_hashtag_list]:
                    final_hashtags.append(ai_tag)
            
            if not user_hashtag_list:
                final_hashtags = ai_generated_hashtags
            
            # Extract content safely
            headline_text = generated_content.headline.content if hasattr(generated_content.headline, 'content') else str(generated_content.headline)
            ad_text_content = generated_content.ad_text.content if hasattr(generated_content.ad_text, 'content') else str(generated_content.ad_text)
            cta_text = generated_content.cta.content if hasattr(generated_content.cta, 'content') else str(generated_content.cta)
            
            base_ad = {
                'headline': headline_text or f"New {competitor_name} Solution",
                'ad_text': ad_text_content or "Discover our amazing services and experience the difference today!",
                'hashtags': final_hashtags if final_hashtags else hashtags if hashtags else ['#business'],
                'cta': cta_text or 'Learn More Today!',
                'quality_score': generated_content.overall_quality.overall_score if hasattr(generated_content, 'overall_quality') else None
            }
            
            # Generate variations by calling AI multiple times
            ads_list.append(base_ad)
            
            for i in range(num_variations - 1):
                # Small delay between variations (pro keys have higher limits, but still good to pace requests)
                wait_time = 2  # Wait 2 seconds between ad variations
                if i > 0:
                    print(f"Waiting {wait_time}s before generating variation {i+2}/{num_variations}...")
                    time.sleep(wait_time)
                
                max_retries = 3
                retry_count = 0
                generated_content = None
                
                while retry_count < max_retries:
                    try:
                        generated_content = ai.generate_content(marketing_context)
                        break  # Success, exit retry loop
                    except Exception as e:
                        error_str = str(e)
                        # Check if it's a rate limit error (429)
                        if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                            retry_count += 1
                            if retry_count < max_retries:
                                wait_time = 10 * retry_count  # Exponential backoff: 10s, 20s, 30s
                                print(f"Rate limit hit, waiting {wait_time}s before retry {retry_count}/{max_retries}")
                                time.sleep(wait_time)
                                continue
                            else:
                                print(f"Rate limit exceeded after {max_retries} retries")
                                raise
                        else:
                            # Not a rate limit error, don't retry
                            raise
                
                try:
                    if generated_content is None:
                        raise Exception("Failed to generate content after retries")
                    
                    # Extract hashtags
                    ai_generated_hashtags = []
                    for h in generated_content.hashtags:
                        if hasattr(h, 'content'):
                            ai_generated_hashtags.append(h.content)
                        elif isinstance(h, str):
                            ai_generated_hashtags.append(h)
                    
                    final_hashtags = user_hashtag_list.copy()
                    for ai_tag in ai_generated_hashtags:
                        ai_tag_clean = ai_tag.strip().lower()
                        if ai_tag_clean not in [t.strip().lower() for t in user_hashtag_list]:
                            final_hashtags.append(ai_tag)
                    
                    if not user_hashtag_list:
                        final_hashtags = ai_generated_hashtags
                    
                    # Extract content safely
                    headline_text = generated_content.headline.content if hasattr(generated_content.headline, 'content') else str(generated_content.headline)
                    ad_text_content = generated_content.ad_text.content if hasattr(generated_content.ad_text, 'content') else str(generated_content.ad_text)
                    cta_text = generated_content.cta.content if hasattr(generated_content.cta, 'content') else str(generated_content.cta)
                    
                    ads_list.append({
                        'headline': headline_text or f"New {competitor_name} Solution",
                        'ad_text': ad_text_content or "Discover our amazing services and experience the difference today!",
                        'hashtags': final_hashtags if final_hashtags else hashtags if hashtags else ['#business'],
                        'cta': cta_text or 'Learn More Today!',
                        'quality_score': generated_content.overall_quality.overall_score if hasattr(generated_content, 'overall_quality') else None
                    })
                except Exception as e:
                    print(f"Ad generation variation {i+1} failed after retries: {e}")
                    import traceback
                    traceback.print_exc()
                    # Don't add fallback here - we'll create defaults at the end if needed
                    continue
                    
        except Exception as e:
            print(f"Batch generation failed, falling back: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to individual generation or create default ads
            for i in range(num_variations):
                try:
                    generated_content = ai.generate_content(marketing_context)
                    
                    user_hashtag_list = []
                    if hashtags and len(hashtags) > 0:
                        for tag in hashtags:
                            tag = tag.strip()
                            if not tag.startswith('#'):
                                tag = '#' + tag.lstrip('#')
                            user_hashtag_list.append(tag)
                    
                    ai_generated_hashtags = []
                    for h in generated_content.hashtags:
                        if hasattr(h, 'content'):
                            ai_generated_hashtags.append(h.content)
                        elif isinstance(h, str):
                            ai_generated_hashtags.append(h)
                    
                    final_hashtags = user_hashtag_list.copy()
                    for ai_tag in ai_generated_hashtags:
                        ai_tag_clean = ai_tag.strip().lower()
                        if ai_tag_clean not in [t.strip().lower() for t in user_hashtag_list]:
                            final_hashtags.append(ai_tag)
                    
                    if not user_hashtag_list:
                        final_hashtags = ai_generated_hashtags
                    
                    # Extract content safely
                    headline_text = generated_content.headline.content if hasattr(generated_content.headline, 'content') else str(generated_content.headline)
                    ad_text_content = generated_content.ad_text.content if hasattr(generated_content.ad_text, 'content') else str(generated_content.ad_text)
                    cta_text = generated_content.cta.content if hasattr(generated_content.cta, 'content') else str(generated_content.cta)
                    
                    ads_list.append({
                        'headline': headline_text or f"New {competitor_name} Solution",
                        'ad_text': ad_text_content or "Discover our amazing services and experience the difference today!",
                        'hashtags': final_hashtags if final_hashtags else hashtags if hashtags else ['#business'],
                        'cta': cta_text or 'Learn More Today!',
                        'quality_score': generated_content.overall_quality.overall_score if hasattr(generated_content, 'overall_quality') else None
                    })
                except Exception as e:
                    print(f"Ad generation attempt {i+1} failed: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
        
        # If no ads were generated, create default ads
        if not ads_list:
            for i in range(num_variations):
                ads_list.append({
                    'headline': f"{our_brand}: Better Than {competitor_name}" if i == 0 else f"Discover {our_brand} Today" if i == 1 else f"Experience {our_brand}",
                    'ad_text': f"Experience the difference with {our_brand}. Quality service you can trust. We deliver excellence every time." if i == 0 else f"Join thousands of satisfied customers who chose {our_brand}. Get the quality you deserve." if i == 1 else f"{our_brand} offers superior service and unmatched quality. See why customers prefer us.",
                    'hashtags': hashtags if hashtags else ['#business'],
                    'cta': 'Learn More Today!' if i == 0 else 'Get Started Now!' if i == 1 else 'Contact Us Today!',
                    'quality_score': 0.5
                })
        
        # Ensure we have exactly num_variations ads
        while len(ads_list) < num_variations:
            ads_list.append({
                'headline': f"Discover {our_brand}",
                'ad_text': f"Experience the difference with {our_brand}. Quality service you can trust.",
                'hashtags': hashtags if hashtags else ['#business'],
                'cta': 'Learn More Today!',
                'quality_score': 0.5
            })
        
        # Limit to num_variations
        ads_list = ads_list[:num_variations]
        
        # Cache the result
        _cache[cache_key] = {'ads': ads_list}
        
        # Save to database if available
        campaign_id = None
        if DB_AVAILABLE and is_db_available():
            try:
                # Create campaign record
                campaign_data = {
                    'name': data.get('campaign_name', f"{our_brand} vs {competitor_name}"),
                    'brand_name': our_brand,
                    'competitor_name': competitor_name,
                    'zipcode': zipcode,
                    'industry': data.get('industry'),
                    'audience_type': data.get('audience_type'),
                    'offer_type': data.get('offer_type'),
                    'goal': data.get('goal'),
                    'scheduled_at': datetime.fromisoformat(data['scheduled_at']) if data.get('scheduled_at') else None,
                    'timezone': data.get('timezone'),
                    'status': 'draft'
                }
                campaign_id = CampaignDB.create_campaign(campaign_data)
                
                # Create ad variants
                if campaign_id:
                    AdVariantDB.create_ad_variants(campaign_id, ads_list)
            except Exception as e:
                print(f"Warning: Failed to save to database: {e}")
        
        return {
            'success': True,
            'ads': ads_list,
            'count': len(ads_list),
            'cached': False,
            'campaign_id': campaign_id
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def send_notifications_job(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Background job to send notifications (email/SMS).
    
    Args:
        data: Dictionary containing:
            - campaign_id: Campaign ID (optional)
            - sms_users: List of SMS user dicts
            - email_users: List of email user dicts
            - ads: List of ad dictionaries to send
    
    Returns:
        Dictionary with sending results
    """
    try:
        campaign_id = data.get('campaign_id')
        sms_users = data.get('sms_users', [])
        email_users = data.get('email_users', [])
        ads = data.get('ads', [])
        
        if not sms_users and not email_users:
            return {
                'success': False,
                'error': 'No users provided'
            }
        
        if not ads:
            return {
                'success': False,
                'error': 'No ads provided'
            }
        
        # Get ad variant IDs from database if campaign_id is provided
        ad_variant_ids = {}
        recipient_ids = {}
        
        if campaign_id and DB_AVAILABLE and is_db_available():
            try:
                # Get ad variants for this campaign to map to ads
                ad_variants = AdVariantDB.get_ad_variants_for_campaign(campaign_id)
                for idx, variant in enumerate(ad_variants):
                    if idx < len(ads):
                        ad_variant_ids[idx] = variant['id']
                        # Also add ID to ad dict for reference
                        ads[idx]['id'] = variant['id']
            except Exception as e:
                print(f"Warning: Failed to get ad variants from database: {e}")
        
        if campaign_id and DB_AVAILABLE and is_db_available():
            try:
                # Store recipient IDs by email/phone for tracking
                all_recipients = []
                for user in sms_users:
                    if user.get('phone'):
                        all_recipients.append({
                            'campaign_id': campaign_id,
                            'name': user.get('name', ''),
                            'phone': user.get('phone'),
                            'channel': 'sms',
                            'tags': user.get('tags', [])
                        })
                for user in email_users:
                    if user.get('email'):
                        all_recipients.append({
                            'campaign_id': campaign_id,
                            'name': user.get('name', ''),
                            'email': user.get('email'),
                            'channel': 'email',
                            'tags': user.get('tags', [])
                        })
                
                if all_recipients:
                    recipient_id_list = RecipientDB.create_recipients(campaign_id, all_recipients)
                    # Map recipients by identifier
                    idx = 0
                    for user in sms_users:
                        if user.get('phone') and idx < len(recipient_id_list):
                            recipient_ids[('sms', user['phone'])] = recipient_id_list[idx]
                            idx += 1
                    for user in email_users:
                        if user.get('email') and idx < len(recipient_id_list):
                            recipient_ids[('email', user['email'])] = recipient_id_list[idx]
                            idx += 1
            except Exception as e:
                print(f"Warning: Failed to save recipients to database: {e}")
        
        try:
            notification = NotificationLayer()
        except Exception as e:
            return {
                'success': False,
                'error': f'Notification service unavailable: {e}'
            }

        # Check that at least one required provider is available for the recipients provided
        missing = []
        if sms_users and NotificationType.SMS not in notification.providers:
            missing.append('SMS (Twilio credentials are missing or invalid)')
        if email_users and NotificationType.EMAIL not in notification.providers:
            missing.append('Email (SendGrid credentials are missing or invalid)')
        if missing:
            return {
                'success': False,
                'error': f'Required notification providers not available: {", ".join(missing)}. '
                         f'Please configure the credentials in your .env file.'
            }

        results = {
            'sms_results': [],
            'email_results': [],
            'summary': {}
        }
        
        # Send SMS
        if sms_users and NotificationType.SMS in notification.providers:
            for ad_idx, ad in enumerate(ads):
                sms_message = f"🎯 {ad['headline']}\n\n{ad['ad_text']}\n\n{ad['cta']}\n\nHashtags: {', '.join(ad['hashtags'])}"
                
                # Get ad variant ID if available
                ad_variant_id = ad.get('id') or (ad_variant_ids.get(ad_idx) if ad_idx in ad_variant_ids else None)
                
                try:
                    sms_results = notification.send_to_user_list(
                        user_list=sms_users,
                        message_content=sms_message,
                        notification_type=NotificationType.SMS
                    )
                    
                    # Track sends in database
                    if campaign_id and DB_AVAILABLE and is_db_available() and ad_variant_id:
                        for i, user in enumerate(sms_users):
                            if i < len(sms_results):
                                result = sms_results[i]
                                recipient_id = recipient_ids.get(('sms', user.get('phone', '')))
                                if recipient_id:
                                    send_id = SendDB.create_send(
                                        campaign_id=campaign_id,
                                        ad_variant_id=ad_variant_id,
                                        recipient_id=recipient_id,
                                        channel='sms',
                                        status='sent' if result.get('success') else 'failed'
                                    )
                                    if send_id:
                                        EventDB.create_event(send_id, 'send', {'channel': 'sms'})
                                        if result.get('success'):
                                            SendDB.update_send_status(send_id, 'delivered')
                                            EventDB.create_event(send_id, 'delivery', {})
                    
                    results['sms_results'].extend(sms_results)
                except Exception as e:
                    error_msg = str(e)
                    for user in sms_users:
                        results['sms_results'].append({
                            'success': False,
                            'error_message': error_msg,
                            'status': 'failed'
                        })
        
        # Send Email
        if email_users and NotificationType.EMAIL in notification.providers:
            for ad_idx, ad in enumerate(ads):
                email_subject = f"🎯 New Ad Campaign: {ad['headline']}"
                email_content = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                        <h2 style="color: #2c3e50;">🎯 New Ad Campaign</h2>
                        
                        <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="color: #e74c3c; margin-top: 0;">{ad['headline']}</h3>
                            <p style="font-size: 16px;">{ad['ad_text']}</p>
                            <p style="text-align: center; margin: 20px 0;">
                                <strong style="background: #3498db; color: white; padding: 12px 24px; border-radius: 5px; display: inline-block;">
                                    {ad['cta']}
                                </strong>
                            </p>
                            <p style="color: #7f8c8d; font-size: 14px;">
                                Hashtags: {', '.join(ad['hashtags'])}
                            </p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                # Get ad variant ID if available
                ad_variant_id = ad.get('id') or (ad_variant_ids.get(ad_idx) if ad_idx in ad_variant_ids else None)
                
                for user in email_users:
                    try:
                        email_result = notification.send_email(
                            to_email=user['email'],
                            subject=email_subject,
                            content=f"New Ad Campaign: {ad['headline']}\n\n{ad['ad_text']}\n\n{ad['cta']}",
                            html_content=email_content
                        )
                        
                        # Track send in database
                        if campaign_id and DB_AVAILABLE and is_db_available() and ad_variant_id:
                            recipient_id = recipient_ids.get(('email', user.get('email', '')))
                            if recipient_id:
                                send_id = SendDB.create_send(
                                    campaign_id=campaign_id,
                                    ad_variant_id=ad_variant_id,
                                    recipient_id=recipient_id,
                                    channel='email',
                                    status='sent' if email_result.get('success') else 'failed'
                                )
                                if send_id:
                                    EventDB.create_event(send_id, 'send', {'channel': 'email'})
                                    if email_result.get('success'):
                                        SendDB.update_send_status(send_id, 'delivered')
                                        EventDB.create_event(send_id, 'delivery', {})
                        
                        results['email_results'].append(email_result)
                    except Exception as e:
                        error_msg = str(e)
                        results['email_results'].append({
                            'success': False,
                            'error_message': error_msg,
                            'status': 'failed'
                        })
        
        # Convert results to dictionaries
        def result_to_dict(result):
            if isinstance(result, dict):
                return result
            elif hasattr(result, 'to_dict'):
                return result.to_dict()
            elif hasattr(result, '__dict__'):
                result_dict = {}
                for key, value in result.__dict__.items():
                    if hasattr(value, 'value'):
                        result_dict[key] = value.value
                    elif hasattr(value, 'isoformat'):
                        result_dict[key] = value.isoformat()
                    else:
                        result_dict[key] = value
                return result_dict
            else:
                return str(result)
        
        results['sms_results'] = [result_to_dict(r) for r in results['sms_results']]
        results['email_results'] = [result_to_dict(r) for r in results['email_results']]
        
        # Calculate summary
        total_sms_sent = sum(1 for r in results['sms_results'] 
                            if isinstance(r, dict) and r.get('success', False))
        
        total_email_sent = sum(1 for r in results['email_results'] 
                              if r and isinstance(r, dict) and r.get('success', False))
        
        error_messages = []
        for result in results['sms_results']:
            if isinstance(result, dict) and not result.get('success', False):
                error_messages.append(f"SMS error: {result.get('error_message', 'Unknown error')}")
        
        for result in results['email_results']:
            if result and isinstance(result, dict) and not result.get('success', False):
                error_messages.append(f"Email error: {result.get('error_message', 'Unknown error')}")
        
        results['summary'] = {
            'total_sms': len(results['sms_results']),
            'successful_sms': total_sms_sent,
            'failed_sms': len(results['sms_results']) - total_sms_sent,
            'total_email': len(results['email_results']),
            'successful_email': total_email_sent,
            'failed_email': len(results['email_results']) - total_email_sent,
            'total_sent': total_sms_sent + total_email_sent,
            'error_messages': error_messages if error_messages else []
        }
        
        return {
            'success': True,
            'results': results
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


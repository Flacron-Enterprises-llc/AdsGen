"""
Main AI Generation Layer orchestrator class.
"""

import re
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from ..providers.gemini_provider import GeminiProvider
from ..providers.mock_provider import MockProvider
from ..models.content_types import GeneratedContent, ContentPiece, ContentQuality, ContentType, ContentStatus
from ..templates.prompt_templates import PromptTemplates
from ..exceptions import AIGenerationError, ProviderError, ContentValidationError


class AIGenerationLayer:
    """
    Main orchestrator class for the AI Generation Layer module.
    
    This class coordinates content generation using LLM providers and prompt templates
    to create marketing content from processed context data.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the AI Generation Layer with configuration.
        
        Args:
            config: Configuration dictionary with options:
                - provider: LLM provider configuration (default: GeminiProvider)
                - templates: Prompt template configuration
                - validation: Content validation configuration
                - global_settings: Global settings for all components
        """
        self.config = config or {}
        self.global_config = self.config.get("global_settings", {})
        
        # Initialize provider (use GeminiProvider by default)
        provider_config = self.config.get("provider", {})
        provider_type = provider_config.get("type", "gemini")  # Default to gemini
        
        if provider_type == "gemini":
            self.provider = GeminiProvider(provider_config)
        else:
            self.provider = MockProvider(provider_config)
        
        # Initialize prompt templates
        templates_config = self.config.get("templates", {})
        self.templates = PromptTemplates(templates_config)
        
        # Generation statistics
        self.stats = {
            "total_generated": 0,
            "successful": 0,
            "failed": 0,
            "content_types": {
                "headline": {"generated": 0, "successful": 0, "failed": 0},
                "ad_text": {"generated": 0, "successful": 0, "failed": 0},
                "hashtags": {"generated": 0, "successful": 0, "failed": 0},
                "cta": {"generated": 0, "successful": 0, "failed": 0}
            }
        }
    
    def generate_content(self, marketing_context: Dict[str, Any]) -> GeneratedContent:
        """
        Generate complete marketing content from context.
        
        Args:
            marketing_context: Marketing context from Processing Layer
            
        Returns:
            GeneratedContent object with all content pieces
            
        Raises:
            AIGenerationError: If content generation fails
        """
        try:
            self.stats["total_generated"] += 1
            
            # Generate individual content pieces
            headline = self._generate_headline(marketing_context)
            ad_text = self._generate_ad_text(marketing_context)
            hashtags = self._generate_hashtags(marketing_context)
            cta = self._generate_cta(marketing_context)
            
            # Calculate overall quality
            overall_quality = self._calculate_overall_quality(headline, ad_text, hashtags, cta, marketing_context)
            
            # Create generated content object
            generated_content = GeneratedContent(
                headline=headline,
                ad_text=ad_text,
                hashtags=hashtags,
                cta=cta,
                overall_quality=overall_quality,
                generation_metadata={
                    "provider": self.provider.get_model_info(),
                    "context_summary": self._create_context_summary(marketing_context),
                    "generation_timestamp": datetime.now().isoformat()
                }
            )
            
            self.stats["successful"] += 1
            return generated_content
            
        except Exception as e:
            self.stats["failed"] += 1
            raise AIGenerationError(f"Content generation failed: {str(e)}") from e
    
    def generate_headline_only(self, marketing_context: Dict[str, Any]) -> ContentPiece:
        """
        Generate only a headline from context.
        
        Args:
            marketing_context: Marketing context from Processing Layer
            
        Returns:
            ContentPiece object with headline
            
        Raises:
            AIGenerationError: If headline generation fails
        """
        try:
            return self._generate_headline(marketing_context)
        except Exception as e:
            raise AIGenerationError(f"Headline generation failed: {str(e)}") from e
    
    def generate_ad_text_only(self, marketing_context: Dict[str, Any]) -> ContentPiece:
        """
        Generate only ad text from context.
        
        Args:
            marketing_context: Marketing context from Processing Layer
            
        Returns:
            ContentPiece object with ad text
            
        Raises:
            AIGenerationError: If ad text generation fails
        """
        try:
            return self._generate_ad_text(marketing_context)
        except Exception as e:
            raise AIGenerationError(f"Ad text generation failed: {str(e)}") from e
    
    def generate_hashtags_only(self, marketing_context: Dict[str, Any]) -> List[ContentPiece]:
        """
        Generate only hashtags from context.
        
        Args:
            marketing_context: Marketing context from Processing Layer
            
        Returns:
            List of ContentPiece objects with hashtags
            
        Raises:
            AIGenerationError: If hashtag generation fails
        """
        try:
            return self._generate_hashtags(marketing_context)
        except Exception as e:
            raise AIGenerationError(f"Hashtag generation failed: {str(e)}") from e
    
    def generate_cta_only(self, marketing_context: Dict[str, Any]) -> ContentPiece:
        """
        Generate only CTA from context.
        
        Args:
            marketing_context: Marketing context from Processing Layer
            
        Returns:
            ContentPiece object with CTA
            
        Raises:
            AIGenerationError: If CTA generation fails
        """
        try:
            return self._generate_cta(marketing_context)
        except Exception as e:
            raise AIGenerationError(f"CTA generation failed: {str(e)}") from e
    
    def _generate_headline(self, context: Dict[str, Any]) -> ContentPiece:
        """Generate headline content."""
        try:
            self.stats["content_types"]["headline"]["generated"] += 1
            
            prompt = self.templates.generate_headline_prompt(context)
            content = self.provider.generate_content(prompt)
            
            # Clean and validate headline
            content = self._clean_content(content)
            quality_score = self._validate_headline(content, context)
            
            content_piece = ContentPiece(
                content_type=ContentType.HEADLINE,
                content=content,
                status=ContentStatus.GENERATED,
                quality_score=quality_score,
                generation_timestamp=datetime.now().isoformat()
            )
            
            self.stats["content_types"]["headline"]["successful"] += 1
            return content_piece
            
        except Exception as e:
            self.stats["content_types"]["headline"]["failed"] += 1
            raise
    
    def _generate_ad_text(self, context: Dict[str, Any]) -> ContentPiece:
        """Generate ad text content."""
        try:
            self.stats["content_types"]["ad_text"]["generated"] += 1
            
            prompt = self.templates.generate_ad_text_prompt(context)
            content = self.provider.generate_content(prompt)
            
            # Clean and validate ad text
            content = self._clean_content(content)
            quality_score = self._validate_ad_text(content, context)
            
            content_piece = ContentPiece(
                content_type=ContentType.AD_TEXT,
                content=content,
                status=ContentStatus.GENERATED,
                quality_score=quality_score,
                generation_timestamp=datetime.now().isoformat()
            )
            
            self.stats["content_types"]["ad_text"]["successful"] += 1
            return content_piece
            
        except Exception as e:
            self.stats["content_types"]["ad_text"]["failed"] += 1
            raise
    
    def _generate_hashtags(self, context: Dict[str, Any]) -> List[ContentPiece]:
        """Generate hashtag content."""
        try:
            self.stats["content_types"]["hashtags"]["generated"] += 1
            
            prompt = self.templates.generate_hashtags_prompt(context)
            content = self.provider.generate_content(prompt)
            
            # Parse hashtags from response
            hashtags = self._parse_hashtags(content)
            
            # Create content pieces for each hashtag
            content_pieces = []
            for i, hashtag in enumerate(hashtags):
                quality_score = self._validate_hashtag(hashtag, context)
                
                content_piece = ContentPiece(
                    content_type=ContentType.HASHTAGS,
                    content=hashtag,
                    status=ContentStatus.GENERATED,
                    quality_score=quality_score,
                    metadata={"hashtag_index": i, "total_hashtags": len(hashtags)},
                    generation_timestamp=datetime.now().isoformat()
                )
                content_pieces.append(content_piece)
            
            self.stats["content_types"]["hashtags"]["successful"] += 1
            return content_pieces
            
        except Exception as e:
            self.stats["content_types"]["hashtags"]["failed"] += 1
            raise
    
    def _generate_cta(self, context: Dict[str, Any]) -> ContentPiece:
        """Generate CTA content."""
        try:
            self.stats["content_types"]["cta"]["generated"] += 1
            
            prompt = self.templates.generate_cta_prompt(context)
            content = self.provider.generate_content(prompt)
            
            # Clean and validate CTA
            content = self._clean_content(content)
            quality_score = self._validate_cta(content, context)
            
            content_piece = ContentPiece(
                content_type=ContentType.CTA,
                content=content,
                status=ContentStatus.GENERATED,
                quality_score=quality_score,
                generation_timestamp=datetime.now().isoformat()
            )
            
            self.stats["content_types"]["cta"]["successful"] += 1
            return content_piece
            
        except Exception as e:
            self.stats["content_types"]["cta"]["failed"] += 1
            raise
    
    def _clean_content(self, content: str) -> str:
        """Clean generated content."""
        # Remove quotes if wrapped
        content = content.strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        elif content.startswith("'") and content.endswith("'"):
            content = content[1:-1]

        # Strip URLs (including UTM-laden links) that the model may echo back
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'www\.\S+', '', content)

        # Remove extra whitespace
        content = re.sub(r'\s+', ' ', content).strip()

        return content
    
    def _parse_hashtags(self, content: str) -> List[str]:
        """Parse hashtags from generated content."""
        # Find all hashtags in the content
        hashtags = re.findall(r'#\w+', content)
        
        # If no hashtags found, try splitting by spaces and adding # if needed
        if not hashtags:
            words = content.split()
            hashtags = []
            for word in words:
                word = word.strip()
                if word.startswith('#'):
                    hashtags.append(word)
                elif word.isalnum():
                    hashtags.append(f"#{word}")
        
        # Limit to 5 hashtags maximum
        return hashtags[:5]
    
    def _validate_headline(self, content: str, context: Dict[str, Any]) -> float:
        """Validate headline quality."""
        score = 1.0
        
        # Length check (under 60 characters)
        if len(content) > 60:
            score -= 0.2
        
        # Check for generic phrases
        generic_phrases = ["the best", "number one", "top rated", "premium quality"]
        if any(phrase in content.lower() for phrase in generic_phrases):
            score -= 0.1
        
        # Check for proper capitalization
        if not content[0].isupper():
            score -= 0.1
        
        return max(0.0, score)
    
    def _validate_ad_text(self, content: str, context: Dict[str, Any]) -> float:
        """Validate ad text quality."""
        score = 1.0
        
        # Length check (2-3 sentences)
        sentences = content.count('.') + content.count('!') + content.count('?')
        if sentences < 2 or sentences > 4:
            score -= 0.2
        
        # Check for benefit-focused language
        benefit_words = ["benefit", "advantage", "value", "save", "improve", "enhance", "boost"]
        if not any(word in content.lower() for word in benefit_words):
            score -= 0.1
        
        return max(0.0, score)
    
    def _validate_hashtag(self, content: str, context: Dict[str, Any]) -> float:
        """Validate hashtag quality."""
        score = 1.0
        
        # Check hashtag format
        if not content.startswith('#'):
            score -= 0.3
        
        # Check length (not too long)
        if len(content) > 30:
            score -= 0.2
        
        # Check for proper formatting
        if not re.match(r'^#[a-zA-Z0-9_]+$', content):
            score -= 0.2
        
        return max(0.0, score)
    
    def _validate_cta(self, content: str, context: Dict[str, Any]) -> float:
        """Validate CTA quality."""
        score = 1.0
        
        # Length check (under 50 characters)
        if len(content) > 50:
            score -= 0.2
        
        # Check for action words
        action_words = ["get", "buy", "try", "learn", "discover", "start", "join", "contact", "call"]
        if not any(word in content.lower() for word in action_words):
            score -= 0.2
        
        # Check for generic CTAs
        generic_ctas = ["learn more", "click here", "read more"]
        if any(cta in content.lower() for cta in generic_ctas):
            score -= 0.1
        
        return max(0.0, score)
    
    def _calculate_overall_quality(self, headline: ContentPiece, ad_text: ContentPiece,
                                 hashtags: List[ContentPiece], cta: ContentPiece,
                                 context: Dict[str, Any]) -> ContentQuality:
        """Calculate overall content quality."""
        # Individual quality scores
        headline_score = headline.quality_score
        ad_text_score = ad_text.quality_score
        hashtag_scores = [h.quality_score for h in hashtags]
        cta_score = cta.quality_score
        
        # Calculate averages
        readability_score = (headline_score + ad_text_score + cta_score) / 3
        engagement_score = self._calculate_engagement_score(headline, ad_text, cta)
        brand_alignment_score = self._calculate_brand_alignment_score(headline, ad_text, hashtags, cta, context)
        tone_consistency_score = self._calculate_tone_consistency_score(headline, ad_text, cta, context)
        length_appropriateness = self._calculate_length_appropriateness(headline, ad_text, cta)
        
        # Create quality object
        quality = ContentQuality(
            readability_score=readability_score,
            engagement_score=engagement_score,
            brand_alignment_score=brand_alignment_score,
            tone_consistency_score=tone_consistency_score,
            length_appropriateness=length_appropriateness
        )
        
        # Calculate overall score
        quality.calculate_overall_score()
        
        # Add quality issues and suggestions
        quality.quality_issues = self._identify_quality_issues(quality)
        quality.suggestions = self._generate_quality_suggestions(quality, context)
        
        return quality
    
    def _calculate_engagement_score(self, headline: ContentPiece, ad_text: ContentPiece, cta: ContentPiece) -> float:
        """Calculate engagement score based on content characteristics."""
        score = 0.5  # Base score
        
        # Headline engagement indicators
        headline_lower = headline.content.lower()
        if any(word in headline_lower for word in ["new", "exclusive", "limited", "breakthrough"]):
            score += 0.2
        if any(word in headline_lower for word in ["free", "save", "win", "get"]):
            score += 0.1
        
        # Ad text engagement indicators
        ad_text_lower = ad_text.content.lower()
        if any(word in ad_text_lower for word in ["now", "today", "immediately", "instant"]):
            score += 0.1
        if any(word in ad_text_lower for word in ["you", "your", "transform", "achieve"]):
            score += 0.1
        
        # CTA engagement indicators
        cta_lower = cta.content.lower()
        if any(word in cta_lower for word in ["now", "today", "free", "limited"]):
            score += 0.1
        
        return min(1.0, score)
    
    def _calculate_brand_alignment_score(self, headline: ContentPiece, ad_text: ContentPiece,
                                       hashtags: List[ContentPiece], cta: ContentPiece,
                                       context: Dict[str, Any]) -> float:
        """Calculate brand alignment score."""
        # This would typically involve more sophisticated brand analysis
        # For now, use a simple approach based on tone consistency
        tone_info = context.get("tone_analysis", {})
        primary_tone = tone_info.get("primary_tone", "professional")
        
        # Check if content aligns with expected tone
        score = 0.7  # Base alignment score
        
        # Add points for tone-appropriate language
        if primary_tone == "local":
            local_words = ["local", "community", "neighborhood", "family"]
            content_text = f"{headline.content} {ad_text.content} {cta.content}".lower()
            if any(word in content_text for word in local_words):
                score += 0.2
        elif primary_tone == "corporate":
            corporate_words = ["professional", "expert", "solutions", "enterprise"]
            content_text = f"{headline.content} {ad_text.content} {cta.content}".lower()
            if any(word in content_text for word in corporate_words):
                score += 0.2
        
        return min(1.0, score)
    
    def _calculate_tone_consistency_score(self, headline: ContentPiece, ad_text: ContentPiece,
                                        cta: ContentPiece, context: Dict[str, Any]) -> float:
        """Calculate tone consistency across content pieces."""
        # Simple tone consistency check
        # In a real implementation, this would use NLP analysis
        return 0.8  # Placeholder score
    
    def _calculate_length_appropriateness(self, headline: ContentPiece, ad_text: ContentPiece, cta: ContentPiece) -> float:
        """Calculate if content lengths are appropriate."""
        score = 1.0
        
        # Headline length (under 60 chars)
        if len(headline.content) > 60:
            score -= 0.3
        
        # Ad text length (reasonable length)
        if len(ad_text.content) > 200:
            score -= 0.2
        
        # CTA length (under 50 chars)
        if len(cta.content) > 50:
            score -= 0.3
        
        return max(0.0, score)
    
    def _identify_quality_issues(self, quality: ContentQuality) -> List[str]:
        """Identify quality issues based on scores."""
        issues = []
        
        if quality.readability_score < 0.6:
            issues.append("Content readability could be improved")
        
        if quality.engagement_score < 0.6:
            issues.append("Content lacks engagement elements")
        
        if quality.brand_alignment_score < 0.6:
            issues.append("Content may not align well with brand tone")
        
        if quality.tone_consistency_score < 0.6:
            issues.append("Tone consistency across content pieces needs improvement")
        
        if quality.length_appropriateness < 0.6:
            issues.append("Content lengths may not be optimal")
        
        return issues
    
    def _generate_quality_suggestions(self, quality: ContentQuality, context: Dict[str, Any]) -> List[str]:
        """Generate suggestions for improving content quality."""
        suggestions = []
        
        if quality.engagement_score < 0.7:
            suggestions.append("Consider adding more compelling action words and urgency indicators")
        
        if quality.readability_score < 0.7:
            suggestions.append("Simplify language and improve sentence structure")
        
        tone_info = context.get("tone_analysis", {})
        primary_tone = tone_info.get("primary_tone", "professional")
        
        if primary_tone == "local" and quality.brand_alignment_score < 0.7:
            suggestions.append("Add more local and community-focused language")
        elif primary_tone == "corporate" and quality.brand_alignment_score < 0.7:
            suggestions.append("Use more professional and authoritative language")
        
        return suggestions
    
    def _create_context_summary(self, context: Dict[str, Any]) -> str:
        """Create a summary of the marketing context."""
        tone_info = context.get("tone_analysis", {})
        keywords = context.get("keyword_patterns", {})
        regional_info = context.get("regional_info", {})
        
        summary_parts = []
        
        if tone_info.get("primary_tone"):
            summary_parts.append(f"Tone: {tone_info['primary_tone']}")
        
        if keywords.get("industry_keywords"):
            industries = ", ".join(keywords["industry_keywords"][:2])
            summary_parts.append(f"Industries: {industries}")
        
        if regional_info.get("primary_region"):
            summary_parts.append(f"Region: {regional_info['primary_region']}")
        
        return " | ".join(summary_parts) if summary_parts else "General context"
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get generation statistics.
        
        Returns:
            Dictionary with generation statistics
        """
        return {
            "statistics": self.stats.copy(),
            "success_rate": (
                self.stats["successful"] / self.stats["total_generated"] * 100
                if self.stats["total_generated"] > 0 else 0
            ),
            "provider_info": self.provider.get_model_info(),
            "last_updated": datetime.now().isoformat()
        }
    
    def reset_statistics(self) -> None:
        """Reset generation statistics."""
        self.stats = {
            "total_generated": 0,
            "successful": 0,
            "failed": 0,
            "content_types": {
                "headline": {"generated": 0, "successful": 0, "failed": 0},
                "ad_text": {"generated": 0, "successful": 0, "failed": 0},
                "hashtags": {"generated": 0, "successful": 0, "failed": 0},
                "cta": {"generated": 0, "successful": 0, "failed": 0}
            }
        }

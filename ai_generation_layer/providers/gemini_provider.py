"""
Gemini Flash LLM provider implementation.
"""

import os
import json
from typing import Dict, Any, Optional
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from ..models.base import BaseLLMProvider
from ..exceptions import ProviderError


class GeminiProvider(BaseLLMProvider):
    """Gemini Flash LLM provider implementation."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize Gemini provider with configuration.
        
        Args:
            config: Configuration dictionary with options:
                - api_key: Gemini API key (can be from env GEMINI_API_KEY)
                - model_name: Model name (default: "gemini-1.5-flash")
                - temperature: Temperature for generation (default: 0.7)
                - max_output_tokens: Maximum output tokens (default: 1024)
                - safety_settings: Safety settings configuration
        """
        super().__init__(config)
        
        # Debug/logging
        self.debug = bool(self.get_config_value("debug") or os.getenv("AI_DEBUG"))

        # Get API key from config or environment or load from .env file
        self.api_key = self.get_config_value("api_key") or os.getenv("GEMINI_API_KEY")
        
        # If still no API key, try to load from .env file in processing_layer folder
        if not self.api_key:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "processing_layer", ".env")
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            if key == "GEMINI_API_KEY":
                                self.api_key = value
                                break
        
        if not self.api_key:
            raise ProviderError("Gemini API key not found in config, environment variable, or .env file")

        masked = self.api_key[:8] + '...' if len(self.api_key) > 8 else self.api_key
        print(f"[GeminiProvider] GEMINI_API_KEY = {masked}")

        # Configure Gemini
        genai.configure(api_key=self.api_key)
        
        # Model configuration
        self.model_name = self.get_config_value("model_name", "gemini-2.5-flash")
        self.temperature = self.get_config_value("temperature", 0.7)
        self.max_output_tokens = self.get_config_value("max_output_tokens", 2048)
        
        # Initialize model
        self.model = genai.GenerativeModel(self.model_name)
        print(f"[GeminiProvider] ✓ Model loaded: {self.model_name}  temp={self.temperature}  max_tokens={self.max_output_tokens}")

        if self.debug:
            print("\n[GeminiProvider] Configured")
            print(f"  Model: {self.model_name}")
            print(f"  Temperature: {self.temperature}")
            print(f"  Max Output Tokens: {self.max_output_tokens}")
            print(f"  TopP: 0.8  TopK: 40")
        
        # Safety settings
        self.safety_settings = self.get_config_value("safety_settings", self._get_default_safety_settings())
        
        # Generation settings
        self.generation_config = genai.types.GenerationConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            top_p=0.8,
            top_k=40
        )
    
    def _get_default_safety_settings(self) -> Dict[str, Any]:
        """Get default safety settings for content generation."""
        return {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }
    
    def generate_content(self, prompt: str, **kwargs) -> str:
        """
        Generate content using Gemini Flash.
        
        Args:
            prompt: The prompt to send to Gemini
            **kwargs: Additional parameters (temperature, max_tokens, etc.)
            
        Returns:
            Generated content as string
            
        Raises:
            ProviderError: If generation fails
        """
        try:
            # Override generation config with kwargs if provided
            generation_config = self.generation_config
            if kwargs:
                config_updates = {}
                if "temperature" in kwargs:
                    config_updates["temperature"] = kwargs["temperature"]
                if "max_tokens" in kwargs:
                    config_updates["max_output_tokens"] = kwargs["max_tokens"]
                if config_updates:
                    generation_config = genai.types.GenerationConfig(**config_updates)
            
            # Generate content
            if self.debug:
                print("\n[GeminiProvider] generate_content()")
                print("  Prompt →\n" + (prompt if isinstance(prompt, str) else str(prompt)))
                print("  GenerationConfig →", {
                    "temperature": generation_config.temperature,
                    "max_output_tokens": generation_config.max_output_tokens,
                })
                print("  SafetySettings →", {k.name: v.name for k, v in self.safety_settings.items()})

            print(f"[GeminiProvider] Calling API… (prompt length={len(str(prompt))} chars)")
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=self.safety_settings
            )
            print(f"[GeminiProvider] ✓ Got response ({len(response.text or '')} chars)")

            # Check if response was blocked
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                raise ProviderError(f"Prompt was blocked: {response.prompt_feedback.block_reason}")
            
            # Check candidate finish reasons
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.finish_reason and candidate.finish_reason != 1:  # 1 = STOP (normal)
                    finish_reasons = {1: "STOP", 2: "MAX_TOKENS", 3: "SAFETY", 4: "RECITATION", 5: "OTHER"}
                    reason = finish_reasons.get(candidate.finish_reason, f"UNKNOWN({candidate.finish_reason})")
                    if candidate.finish_reason == 3:  # SAFETY
                        raise ProviderError(f"Content blocked by safety filters. Try rephrasing your prompt.")
                    else:
                        raise ProviderError(f"Content generation stopped: {reason}")
            
            if not response.text:
                raise ProviderError("No content generated - response was empty")
            
            return response.text.strip()
            
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(f"Gemini generation failed: {str(e)}") from e
    
    def generate_structured_content(self, prompt: str, expected_format: str = "json", **kwargs) -> Dict[str, Any]:
        """
        Generate structured content that can be parsed as JSON.
        
        Args:
            prompt: The prompt to send to Gemini
            expected_format: Expected format ("json", "list", "dict")
            **kwargs: Additional parameters
            
        Returns:
            Parsed structured content
            
        Raises:
            ProviderError: If generation or parsing fails
        """
        try:
            # Add format instruction to prompt
            format_instruction = self._get_format_instruction(expected_format)
            full_prompt = f"{prompt}\n\n{format_instruction}"
            
            # Generate content
            if self.debug:
                print("\n[GeminiProvider] generate_structured_content()")
                print("  Prompt →\n" + full_prompt)
                print("  Expected Format →", expected_format)
            content = self.generate_content(full_prompt, **kwargs)
            
            # Parse based on expected format
            if expected_format == "json":
                return json.loads(content)
            elif expected_format == "list":
                # Try to parse as JSON list, fallback to line splitting
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return [line.strip() for line in content.split('\n') if line.strip()]
            elif expected_format == "dict":
                # Try to parse as JSON, fallback to key-value parsing
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return self._parse_key_value_content(content)
            else:
                return {"content": content}
                
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(f"Structured content generation failed: {str(e)}") from e
    
    def _get_format_instruction(self, expected_format: str) -> str:
        """Get format instruction for structured content generation."""
        if expected_format == "json":
            return "Please respond with valid JSON format only. No additional text or explanations."
        elif expected_format == "list":
            return "Please respond with a list format. Each item on a new line or as a JSON array."
        elif expected_format == "dict":
            return "Please respond with key-value pairs or JSON object format."
        else:
            return "Please respond with clear, structured content."
    
    def _parse_key_value_content(self, content: str) -> Dict[str, Any]:
        """Parse key-value content when JSON parsing fails."""
        result = {}
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()
        
        return result
    
    def is_available(self) -> bool:
        """
        Check if Gemini provider is available and properly configured.
        
        Returns:
            True if available, False otherwise
        """
        try:
            # Test with a simple prompt
            test_response = self.generate_content("Hello, respond with 'OK'")
            return "ok" in test_response.lower()
        except Exception:
            return False
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the current model configuration.
        
        Returns:
            Dictionary with model information
        """
        return {
            "provider": "gemini",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "api_key_configured": bool(self.api_key),
            "available": self.is_available()
        }

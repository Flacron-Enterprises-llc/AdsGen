"""
Gemini LLM provider implementation using the google-generativeai SDK.
"""

import os
import json
from typing import Dict, Any, Optional

import google.generativeai as genai

from ..models.base import BaseLLMProvider
from ..exceptions import ProviderError


class GeminiProvider(BaseLLMProvider):
    """Gemini LLM provider using the google-generativeai SDK."""

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize Gemini provider with configuration.

        Args:
            config: Configuration dictionary with options:
                - api_key: Gemini API key (can be from env GEMINI_API_KEY)
                - model_name: Model name (default: "gemini-2.0-flash")
                - temperature: Temperature for generation (default: 0.7)
                - max_output_tokens: Maximum output tokens (default: 2048)
        """
        super().__init__(config)

        self.debug = bool(self.get_config_value("debug") or os.getenv("AI_DEBUG"))

        # Resolve API key
        self.api_key = self.get_config_value("api_key") or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "processing_layer", ".env"
            )
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            if k.strip() == "GEMINI_API_KEY":
                                self.api_key = v.strip()
                                break

        if not self.api_key:
            raise ProviderError(
                "Gemini API key not found in config, environment variable, or .env file"
            )

        masked = self.api_key[:8] + '...' if len(self.api_key) > 8 else self.api_key
        print(f"[GeminiProvider] GEMINI_API_KEY = {masked}")

        genai.configure(api_key=self.api_key)

        # Model configuration
        self.model_name = self.get_config_value("model_name", "gemini-1.5-flash")
        self.temperature = float(self.get_config_value("temperature", 0.7))
        self.max_output_tokens = int(self.get_config_value("max_output_tokens", 2048))

        self._generation_config = genai.types.GenerationConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            top_p=0.8,
        )
        self._safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]
        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config=self._generation_config,
            safety_settings=self._safety_settings,
        )

        print(
            f"[GeminiProvider] Client ready: model={self.model_name}  "
            f"temp={self.temperature}  max_tokens={self.max_output_tokens}"
        )

        if self.debug:
            print("\n[GeminiProvider] Configured")
            print(f"  Model: {self.model_name}")
            print(f"  Temperature: {self.temperature}")
            print(f"  Max Output Tokens: {self.max_output_tokens}")

    def generate_content(self, prompt: str, **kwargs) -> str:
        """
        Generate content using Gemini.

        Args:
            prompt: The prompt to send to Gemini
            **kwargs: Optional overrides — temperature, max_tokens

        Returns:
            Generated content as string

        Raises:
            ProviderError: If generation fails
        """
        try:
            generation_config = self._generation_config
            if kwargs:
                overrides = {}
                if "temperature" in kwargs:
                    overrides["temperature"] = kwargs["temperature"]
                if "max_tokens" in kwargs:
                    overrides["max_output_tokens"] = kwargs["max_tokens"]
                if overrides:
                    generation_config = genai.types.GenerationConfig(
                        temperature=overrides.get("temperature", self.temperature),
                        max_output_tokens=overrides.get("max_output_tokens", self.max_output_tokens),
                        top_p=0.8,
                    )

            if self.debug:
                print("\n[GeminiProvider] generate_content()")
                print("  Prompt →\n" + str(prompt))

            print(f"[GeminiProvider] Calling API... (prompt length={len(str(prompt))} chars)")
            response = self._model.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=self._safety_settings,
            )
            text = (response.text or "").strip()
            print(f"[GeminiProvider] Got response ({len(text)} chars)")

            if not text:
                raise ProviderError("No content generated — response was empty")

            if response.candidates:
                candidate = response.candidates[0]
                finish = getattr(candidate, 'finish_reason', None)
                if finish and str(finish) not in ('FinishReason.STOP', 'STOP', '1'):
                    if 'SAFETY' in str(finish) or str(finish) == '3':
                        raise ProviderError(
                            "Content blocked by safety filters. Try rephrasing your prompt."
                        )

            return text

        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(f"Gemini generation failed: {str(e)}") from e

    def _get_default_safety_settings(self) -> list:
        """Kept for backward compatibility — returns the SDK safety settings list."""
        return self._safety_settings

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
            format_instruction = self._get_format_instruction(expected_format)
            full_prompt = f"{prompt}\n\n{format_instruction}"

            if self.debug:
                print("\n[GeminiProvider] generate_structured_content()")
                print("  Prompt →\n" + full_prompt)
                print("  Expected Format →", expected_format)
            content = self.generate_content(full_prompt, **kwargs)

            if expected_format == "json":
                return json.loads(content)
            elif expected_format == "list":
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return [line.strip() for line in content.split('\n') if line.strip()]
            elif expected_format == "dict":
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
        for line in content.split('\n'):
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()
        return result

    def is_available(self) -> bool:
        """Check if Gemini provider is available and properly configured."""
        try:
            test_response = self.generate_content("Hello, respond with 'OK'")
            return "ok" in test_response.lower()
        except Exception:
            return False

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model configuration."""
        return {
            "provider": "gemini",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "api_key_configured": bool(self.api_key),
            "available": self.is_available()
        }

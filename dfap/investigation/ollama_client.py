# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M14 Local Ollama LLM Client Adapter

import os
import re
from typing import Any, Dict, List, Optional
import urllib.request as urllib_request
import urllib.error as urllib_error
import json


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama runtime cannot be reached or fails health check."""
    pass


class OllamaClient:
    """Safe, minimal adapter for local Ollama LLM runtime."""

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or self.DEFAULT_BASE_URL).rstrip("/")
        self._configured_model = model or os.environ.get("OLLAMA_MODEL")
        self.timeout = timeout
        self._model: Optional[str] = self._configured_model
        # Performance: cache health check result for 120s to avoid per-request round-trips
        self._health_cache: Optional[dict] = None
        self._health_cache_ts: float = 0.0
        self._health_cache_ttl: float = 120.0

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        # Auto-detect from available local models
        available = self.available_models()
        if not available:
            raise OllamaUnavailableError(f"No local models available at {self.base_url}")
        self._model = available[0]
        return self._model

    def health_check(self, force: bool = False) -> Dict[str, Any]:
        """Verifies local Ollama server connectivity and model availability.
        Caches result for 120s to avoid a round-trip on every investigate() call.
        """
        import time
        now = time.monotonic()
        if not force and self._health_cache is not None and (now - self._health_cache_ts) < self._health_cache_ttl:
            return self._health_cache
        try:
            with urllib_request.urlopen(f"{self.base_url}/api/tags", timeout=min(5.0, self.timeout)) as response:
                if response.status != 200:
                    result = {
                        "status": "UNAVAILABLE",
                        "base_url": self.base_url,
                        "error": f"HTTP {response.status}: {response.read().decode()}",
                        "available_models": []
                    }
                    self._health_cache = result
                    self._health_cache_ts = now
                    return result
                data_bytes = response.read()
                data = json.loads(data_bytes.decode())
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            selected = self._configured_model if (self._configured_model and self._configured_model in models) else (models[0] if models else None)
            # Cache the resolved model so model property never re-discovers
            if selected and not self._model:
                self._model = selected
            result = {
                "status": "OK",
                "base_url": self.base_url,
                "available_models": models,
                "selected_model": selected,
                "models_count": len(models)
            }
            self._health_cache = result
            self._health_cache_ts = now
            return result
        except Exception as e:
            result = {
                "status": "UNAVAILABLE",
                "base_url": self.base_url,
                "error": str(e),
                "available_models": []
            }
            # Don't cache failures longer than 15s
            self._health_cache = result
            self._health_cache_ts = now - (self._health_cache_ttl - 15.0)
            return result

    def available_models(self) -> List[str]:
        """Lists names of models installed in the local Ollama instance."""
        try:
            with urllib_request.urlopen(f"{self.base_url}/api/tags", timeout=min(5.0, self.timeout)) as response:
                if response.status != 200:
                    return []
                data_bytes = response.read()
                data = json.loads(data_bytes.decode())
            return [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        format_json: bool = False
    ) -> Dict[str, Any]:
        """
        Executes generation on the local Ollama instance.
        Enforces temperature=0 by default and strips internal thinking blocks.
        Never exposes raw private thinking/chain-of-thought to caller.
        """
        target_model = self.model
        payload: Dict[str, Any] = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": float(temperature)
            }
        }
        if system:
            payload["system"] = system
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        if format_json:
            payload["format"] = "json"

        try:
            payload_bytes = json.dumps(payload).encode('utf-8')
            req = urllib_request.Request(
                url=f"{self.base_url}/api/generate",
                data=payload_bytes,
                method='POST'
            )
            req.add_header('Content-Type', 'application/json')
            with urllib_request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    raise OllamaUnavailableError(
                        f"Ollama API error ({response.status}): {response.read().decode()}"
                    )
                result = json.loads(response.read().decode())
        except urllib_error.HTTPError as e:
            raise OllamaUnavailableError(
                f"Failed to connect to local Ollama at {self.base_url}: HTTP {e.code} {e.reason}"
            )
        except urllib_error.URLError as e:
            raise OllamaUnavailableError(
                f"Failed to connect to local Ollama at {self.base_url}: {e.reason}"
            )

        raw_response = result.get("response", "")
        # Clean any <think> tags if model embedded thinking in response text
        cleaned_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
        if not cleaned_response and "<think>" in raw_response:
            cleaned_response = ""
        elif not cleaned_response:
            cleaned_response = raw_response.strip()

        return {
            "response": cleaned_response,
            "model": target_model,
            "created_at": result.get("created_at"),
            "done": result.get("done", True),
            "eval_count": result.get("eval_count"),
            "total_duration": result.get("total_duration")
        }

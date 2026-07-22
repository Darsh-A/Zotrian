from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import AISettings


class AICleaningError(RuntimeError):
    pass


@dataclass(slots=True)
class CleaningCandidate:
    annot_key: str
    section: str
    page: str | None
    color: str
    text: str
    comment: str | None


SYSTEM_PROMPT = (
    "You clean scientific paper annotations into markdown. "
    "Fix OCR glitches. Preserve meaning. "
    "Use $...$ / $$...$$ for LaTeX math. "
    "Use **bold** for key terms, *italic* for emphasis. "
    "Merge adjacent annotations on the same concept "
    "with comma-separated annot_key (e.g. \"123,124\"). "
    "Use bullets/pointers when appropriate. "
    "Be concise. No filler. Never invent facts.\n\n"
    "Return only valid JSON:\n"
    '{"items":[{"annot_key":"...","cleaned_note":"..."}]}'
)


class AICleaner:
    cache_version = "1"

    def __init__(self, settings: AISettings):
        self.settings = settings
        provider = settings.provider.lower()
        if provider not in ("gemini", "ollama"):
            raise AICleaningError(f"Unsupported AI provider: {settings.provider}")
        if provider == "gemini" and not settings.api_key:
            raise AICleaningError(
                f"AI cleaning is enabled, but environment variable {settings.api_key_env} is not set."
            )

    def input_signature(self, candidate: CleaningCandidate) -> str:
        payload = {
            "version": self.cache_version,
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "annot_key": candidate.annot_key,
            "section": candidate.section,
            "page": candidate.page,
            "color": candidate.color,
            "text": candidate.text,
            "comment": candidate.comment or "",
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def clean_batch(self, paper: dict[str, Any], candidates: list[CleaningCandidate]) -> dict[str, str]:
        if not candidates:
            return {}

        payload = {
            "paper_title": paper.get("title", ""),
            "paper_year": paper.get("date", ""),
            "items": [
                {
                    "annot_key": item.annot_key,
                    "section": item.section,
                    "page": item.page,
                    "color": item.color,
                    "text": item.text,
                    "comment": item.comment or "",
                }
                for item in candidates
            ],
        }

        response = self._generate_json(payload)
        items = response.get("items")
        if not isinstance(items, list):
            raise AICleaningError("AI response did not contain an items list.")

        cleaned: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            annot_key = str(item.get("annot_key", "")).strip()
            cleaned_note = str(item.get("cleaned_note", "")).strip()
            if annot_key and cleaned_note:
                cleaned[annot_key] = cleaned_note
        return cleaned

    @staticmethod
    def _fix_json_escapes(text: str) -> str:
        text = re.sub(
            r'(?<!\\)\\([a-zA-Z]+)',
            r'\\\\\1',
            text,
        )
        text = re.sub(
            r'(?<!\\)\\(?![\\"/bfnrtu])',
            r'\\\\',
            text,
        )
        return text

    @staticmethod
    def _robust_json_loads(text: str) -> dict[str, Any]:
        fixed = AICleaner._fix_json_escapes(text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as exc:
            raise AICleaningError(
                f"Model returned invalid JSON: {fixed[:500]}"
            ) from exc

    def _generate_json(self, prompt_payload: dict[str, Any]) -> dict[str, Any]:
        provider = self.settings.provider.lower()
        if provider == "ollama":
            return self._generate_ollama(prompt_payload)
        return self._generate_gemini(prompt_payload)

    def _generate_ollama(self, prompt_payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.settings.temperature,
                "num_predict": self.settings.max_output_tokens,
            },
        }
        data = json.dumps(request_payload).encode("utf-8")

        host = self.settings.api_key or "http://localhost:11434"
        endpoint = f"{host.rstrip('/')}/api/chat"
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AICleaningError(f"Ollama API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AICleaningError(f"Ollama API request failed: {exc.reason}") from exc

        try:
            payload = json.loads(raw)
            text = payload["message"]["content"].strip()
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AICleaningError(f"Unexpected Ollama response: {raw}") from exc

        return self._robust_json_loads(text)

    def _generate_gemini(self, prompt_payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(self.settings.model)}:generateContent"
            f"?key={urllib.parse.quote(self.settings.api_key)}"
        )
        request_payload = {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(prompt_payload, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {
                "temperature": self.settings.temperature,
                "maxOutputTokens": self.settings.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        data = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AICleaningError(f"Gemini API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AICleaningError(f"Gemini API request failed: {exc.reason}") from exc

        try:
            payload = json.loads(raw)
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AICleaningError(f"Unexpected Gemini response: {raw}") from exc

        cleaned_text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return self._robust_json_loads(cleaned_text)

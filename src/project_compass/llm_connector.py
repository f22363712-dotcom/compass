"""Unified zero-dependency OpenAI-compatible LLM connector (cloud BYOK + local Ollama).

Pure Python standard library only. Never persists or exposes API keys or local file
paths, skips external calls when SAMPLE_MODE=true, and strips <think> blocks so
hidden model chain-of-thought never leaks into product conclusions or evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_CLOUD_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1/chat/completions"
DEFAULT_CLOUD_MODEL = "deepseek-chat"
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.7"
DEFAULT_MINIMAX_FLASH_MODEL = "MiniMax-M3.1-Flash"
DEFAULT_LOCAL_MODEL = "qwen2.5:7b"

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)
_CREDENTIAL_KV_RE = re.compile(
    r"^(base_url|url|endpoint|api_key|key|token|model|default_model)\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_LLM_STATE_LOCK = Lock()
_OVERRIDE_ENV_SIG: tuple[tuple[str, str], ...] | None = None
_OVERRIDE_PROFILE_ID: str | None = None

_RELEVANT_ENV_KEYS = (
    "SAMPLE_MODE",
    "COMPASS_LLM_API_KEY",
    "COMPASS_CRITIC_API_KEY",
    "MINIMAX_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "COMPASS_LLM_KEY_FILE",
    "COMPASS_LLM_KEY_FILES",
    "COMPASS_LLM_BASE_URL",
    "COMPASS_CRITIC_BASE_URL",
    "OPENAI_BASE_URL",
    "OLLAMA_HOST",
    "COMPASS_LLM_MODEL",
    "COMPASS_CRITIC_MODEL",
)


def is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def strip_model_thinking(text: Any) -> str:
    """Remove <think>...</think> blocks and outer markdown code fences safely."""
    raw = str(text or "")
    if "</think>" in raw.lower() and "<think>" not in raw.lower():
        raw = re.split(r"</think>", raw, maxsplit=1, flags=re.IGNORECASE)[-1]
    cleaned = _THINK_BLOCK_RE.sub("", raw)
    cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()
    if cleaned.startswith("```") and cleaned.endswith("```") and cleaned.count("```") >= 2:
        inner = cleaned[3:-3].strip()
        if "\n" in inner:
            first_line, rest = inner.split("\n", 1)
            if first_line.strip().lower() in {"json", "markdown", "md", "text", ""}:
                cleaned = rest.strip()
            else:
                cleaned = inner
        else:
            cleaned = inner
    return cleaned.strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first valid JSON object from a cleaned LLM reply."""
    cleaned = strip_model_thinking(text)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(cleaned[start : idx + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = cleaned.find("{", start + 1)
    return None


def _normalize_chat_endpoint(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return url
    if path.endswith("/v1"):
        return f"{url}/chat/completions"
    if not path:
        return f"{url}/v1/chat/completions"
    return url


def _is_loopback_url(url: str) -> bool:
    if not url:
        return False
    host = (urlparse(url).hostname or "").strip().lower()
    return host in _LOOPBACK_HOSTS


def parse_llm_credential_file(path_str: str) -> dict[str, str]:
    """Parse single-line API keys or key:value credential notes without exposing paths."""
    if not path_str:
        return {}
    try:
        path = Path(path_str).expanduser()
        if not path.is_file():
            return {}
        raw = path.read_text(encoding="utf-8", errors="ignore")[:2048]
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    bare_candidates: list[str] = []
    for line in raw.splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        kv = _CREDENTIAL_KV_RE.match(token)
        if kv:
            field = kv.group(1).lower()
            val = kv.group(2).strip().strip('"').strip("'")
            if not val:
                continue
            if field in {"base_url", "url", "endpoint"} and "base_url" not in parsed:
                parsed["base_url"] = val
            elif field in {"api_key", "key", "token"} and "api_key" not in parsed:
                parsed["api_key"] = val
            elif field in {"model", "default_model"} and "model" not in parsed:
                parsed["model"] = val
            continue
        bare_candidates.append(token)

    if "api_key" not in parsed and bare_candidates:
        sk_line = next(
            (item for item in bare_candidates if item.startswith("sk-") and not any(ch.isspace() for ch in item)),
            "",
        )
        parsed["api_key"] = sk_line or bare_candidates[0]

    api_key = parsed.get("api_key", "").strip()
    if not api_key and not _is_loopback_url(parsed.get("base_url", "")):
        return {}
    base_url = parsed.get("base_url", "").strip()
    if not base_url and api_key:
        base_url = DEFAULT_MINIMAX_BASE_URL if api_key.startswith("sk-cp-") else DEFAULT_CLOUD_BASE_URL
    if base_url:
        parsed["base_url"] = _normalize_chat_endpoint(base_url)
    return parsed


def _read_key_from_file(path_str: str) -> str:
    return parse_llm_credential_file(path_str).get("api_key", "")


def _env_signature() -> tuple[tuple[str, str], ...]:
    return tuple((key, os.environ.get(key, "")) for key in _RELEVANT_ENV_KEYS)


def _slugify_profile_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", text.strip().lower()).strip("-")
    return slug or "cloud-llm"


def _collect_credential_entries() -> list[dict[str, str]]:
    if is_truthy_env("SAMPLE_MODE"):
        return []

    explicit_model = (
        os.environ.get("COMPASS_LLM_MODEL", "").strip()
        or os.environ.get("COMPASS_CRITIC_MODEL", "").strip()
    )
    entries: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def _add_entry(api_key: str, base_url: str, model: str = "") -> None:
        norm_url = _normalize_chat_endpoint(base_url) if base_url else ""
        if not norm_url and api_key:
            norm_url = DEFAULT_MINIMAX_BASE_URL if api_key.startswith("sk-cp-") else DEFAULT_CLOUD_BASE_URL
        if not norm_url:
            return
        if not api_key and not _is_loopback_url(norm_url):
            return
        pair = (norm_url.casefold(), api_key)
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        entries.append({"api_key": api_key, "base_url": norm_url, "model": model})

    env_base = ""
    for var_name in ("COMPASS_LLM_BASE_URL", "COMPASS_CRITIC_BASE_URL", "OPENAI_BASE_URL"):
        candidate = os.environ.get(var_name, "").strip()
        if candidate:
            env_base = candidate
            break

    explicit_key = (
        os.environ.get("COMPASS_LLM_API_KEY", "").strip()
        or os.environ.get("COMPASS_CRITIC_API_KEY", "").strip()
    )
    if explicit_key or (env_base and _is_loopback_url(_normalize_chat_endpoint(env_base))):
        _add_entry(explicit_key, env_base, explicit_model)

    mm_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if mm_key:
        _add_entry(mm_key, DEFAULT_MINIMAX_BASE_URL, explicit_model)

    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if ds_key:
        _add_entry(ds_key, DEFAULT_CLOUD_BASE_URL, explicit_model)

    oa_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if oa_key:
        oa_base = env_base or (
            DEFAULT_MINIMAX_BASE_URL if oa_key.startswith("sk-cp-") else "https://api.openai.com/v1/chat/completions"
        )
        _add_entry(oa_key, oa_base, explicit_model)

    raw_paths: list[str] = []
    single_file = os.environ.get("COMPASS_LLM_KEY_FILE", "").strip()
    if single_file:
        raw_paths.append(single_file)
    multi_files = os.environ.get("COMPASS_LLM_KEY_FILES", "").strip()
    if multi_files:
        raw_paths.extend(part.strip() for part in multi_files.split(";") if part.strip())

    seen_paths: set[str] = set()
    for p in raw_paths:
        norm_p = str(Path(p).expanduser())
        if norm_p in seen_paths:
            continue
        seen_paths.add(norm_p)
        parsed = parse_llm_credential_file(p)
        if parsed:
            _add_entry(
                parsed.get("api_key", ""),
                parsed.get("base_url", ""),
                parsed.get("model", "") or explicit_model,
            )

    ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
    if ollama_host:
        _add_entry("ollama", ollama_host, explicit_model or DEFAULT_LOCAL_MODEL)

    return entries


def _build_profiles() -> list[dict[str, Any]]:
    entries = _collect_credential_entries()
    if not entries:
        return []

    explicit_model = (
        os.environ.get("COMPASS_LLM_MODEL", "").strip()
        or os.environ.get("COMPASS_CRITIC_MODEL", "").strip()
    )
    profiles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _register(pid: str, label: str, mode: str, model: str, base_url: str, api_key: str) -> None:
        if pid in seen_ids:
            return
        seen_ids.add(pid)
        profiles.append(
            {
                "id": pid,
                "label": label,
                "enabled": True,
                "mode": mode,
                "model": model,
                "base_url": base_url,
                "api_key": api_key or ("ollama" if mode == "local_llm" else ""),
                "provider_label": f"语义增强 · {model}",
            }
        )

    for entry in entries:
        base_url = entry["base_url"]
        api_key = entry["api_key"]
        base_lower = base_url.lower()
        entry_model = entry.get("model", "").strip()
        if _is_loopback_url(base_url):
            m = entry_model or explicit_model or DEFAULT_LOCAL_MODEL
            _register("local-llm", f"本机模型 ({m})", "local_llm", m, base_url, api_key or "ollama")
        elif "minimax" in base_lower or api_key.startswith("sk-cp-"):
            if entry_model and entry_model not in {DEFAULT_MINIMAX_FLASH_MODEL, DEFAULT_MINIMAX_MODEL}:
                _register(_slugify_profile_id(entry_model), entry_model, "cloud_llm", entry_model, base_url, api_key)
            _register("minimax-m3.1-flash", "MiniMax-M3.1-Flash", "cloud_llm", DEFAULT_MINIMAX_FLASH_MODEL, base_url, api_key)
            _register("minimax-m2.7", "MiniMax-M2.7", "cloud_llm", DEFAULT_MINIMAX_MODEL, base_url, api_key)
        elif "deepseek" in base_lower:
            _register("deepseek-chat", "DeepSeek-Chat", "cloud_llm", DEFAULT_CLOUD_MODEL, base_url, api_key)
            if entry_model and entry_model.lower() != DEFAULT_CLOUD_MODEL.lower():
                _register(_slugify_profile_id(entry_model), entry_model, "cloud_llm", entry_model, base_url, api_key)
        else:
            m = entry_model or explicit_model or DEFAULT_CLOUD_MODEL
            _register(_slugify_profile_id(m), m, "cloud_llm", m, base_url, api_key)

    if profiles:
        profiles.append(
            {
                "id": "local",
                "label": "本地检索",
                "enabled": False,
                "mode": "local",
                "model": "",
                "base_url": "",
                "api_key": "",
                "provider_label": "本地检索",
            }
        )
    return profiles


def available_llm_profiles() -> list[dict[str, str]]:
    """Return UI-safe list of selectable LLM/local profiles without exposing secrets or URLs."""
    return [
        {
            "id": str(p["id"]),
            "label": str(p["label"]),
            "mode": str(p["mode"]),
            "model": str(p["model"]),
        }
        for p in _build_profiles()
    ]


def _default_profile(profiles: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not profiles:
        return None
    explicit_model = (
        os.environ.get("COMPASS_LLM_MODEL", "").strip()
        or os.environ.get("COMPASS_CRITIC_MODEL", "").strip()
    )
    if explicit_model:
        for p in profiles:
            if str(p["model"]).casefold() == explicit_model.casefold():
                return p
    for p in profiles:
        if p["id"] == "minimax-m2.7":
            return p
    return next((p for p in profiles if p["enabled"]), profiles[0])


def set_active_llm_profile(profile_id: str | None) -> dict[str, Any]:
    """Activate one configured profile in memory for the current dashboard process."""
    global _OVERRIDE_ENV_SIG, _OVERRIDE_PROFILE_ID
    if is_truthy_env("SAMPLE_MODE"):
        raise ValueError("sample mode cannot switch models")
    profiles = _build_profiles()
    if not profiles:
        raise ValueError("no external LLM profiles are configured")
    target = str(profile_id or "").strip()
    if not target:
        with _LLM_STATE_LOCK:
            _OVERRIDE_ENV_SIG = _env_signature()
            _OVERRIDE_PROFILE_ID = None
        return resolve_llm_config()
    matched = next((p for p in profiles if p["id"] == target), None)
    if matched is None:
        raise ValueError(f"unknown llm profile: {target}")
    with _LLM_STATE_LOCK:
        _OVERRIDE_ENV_SIG = _env_signature()
        _OVERRIDE_PROFILE_ID = matched["id"]
    return resolve_llm_config()


def reset_active_llm_profile() -> None:
    global _OVERRIDE_ENV_SIG, _OVERRIDE_PROFILE_ID
    with _LLM_STATE_LOCK:
        _OVERRIDE_ENV_SIG = None
        _OVERRIDE_PROFILE_ID = None


def resolve_llm_config() -> dict[str, Any]:
    """Resolve optional OpenAI-compatible cloud BYOK or local Ollama configuration."""
    global _OVERRIDE_ENV_SIG, _OVERRIDE_PROFILE_ID
    if is_truthy_env("SAMPLE_MODE"):
        return {
            "enabled": False,
            "mode": "local",
            "model": "",
            "base_url": "",
            "api_key": "",
            "provider_label": "本地检索",
            "active_profile": "local",
        }

    profiles = _build_profiles()
    if not profiles:
        return {
            "enabled": False,
            "mode": "local",
            "model": "",
            "base_url": "",
            "api_key": "",
            "provider_label": "本地检索",
            "active_profile": "local",
        }

    sig = _env_signature()
    override_id: str | None = None
    with _LLM_STATE_LOCK:
        if _OVERRIDE_ENV_SIG is not None and _OVERRIDE_ENV_SIG != sig:
            _OVERRIDE_ENV_SIG = None
            _OVERRIDE_PROFILE_ID = None
        override_id = _OVERRIDE_PROFILE_ID

    chosen = None
    if override_id:
        chosen = next((p for p in profiles if p["id"] == override_id), None)
    if chosen is None:
        chosen = _default_profile(profiles)
    if chosen is None:
        return {
            "enabled": False,
            "mode": "local",
            "model": "",
            "base_url": "",
            "api_key": "",
            "provider_label": "本地检索",
            "active_profile": "local",
        }

    return {
        "enabled": bool(chosen["enabled"]),
        "mode": str(chosen["mode"]),
        "model": str(chosen["model"]),
        "base_url": str(chosen["base_url"]),
        "api_key": str(chosen["api_key"]),
        "provider_label": str(chosen["provider_label"]),
        "active_profile": str(chosen["id"]),
    }


def public_llm_status() -> dict[str, Any]:
    """Return UI-safe LLM capability badge metadata (never exposes secrets or URLs)."""
    cfg = resolve_llm_config()
    profiles = available_llm_profiles()
    return {
        "enabled": bool(cfg["enabled"]),
        "mode": str(cfg["mode"]),
        "model": str(cfg["model"]),
        "provider_label": str(cfg["provider_label"]),
        "active_profile": str(cfg.get("active_profile") or ("local" if not cfg["enabled"] else _slugify_profile_id(cfg["model"]))),
        "profiles": profiles if len(profiles) > 1 else [],
    }


def chat_completion_text(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 900,
    timeout: float = 8.0,
    temperature: float = 0.1,
    response_format: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
) -> tuple[str, str]:
    """Execute one bounded chat completion request and return (cleaned_text, error)."""
    cfg = resolve_llm_config()
    if not cfg["enabled"]:
        return "", "llm_unconfigured"

    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max(64, min(int(max_tokens), 16384)),
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if "m3.1-flash" in str(cfg["model"]).lower():
        effort = (reasoning_effort or os.environ.get("COMPASS_LLM_REASONING_EFFORT", "")).strip() or "low"
        payload["reasoning_effort"] = effort
    elif reasoning_effort and reasoning_effort.strip():
        payload["reasoning_effort"] = reasoning_effort.strip()

    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    req = Request(
        cfg["base_url"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    open_fn = urlopen_fn or urlopen
    bounded_timeout = max(1.0, min(float(timeout), 60.0))
    try:
        with open_fn(req, timeout=bounded_timeout) as resp:
            raw_body = json.loads(resp.read().decode("utf-8"))
        choice = (raw_body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        raw_content = msg.get("content")
        if raw_content is None:
            raw_content = choice.get("text") or ""
        cleaned = strip_model_thinking(str(raw_content))
        if not cleaned:
            return "", "empty_model_response"
        return cleaned, ""
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        return "", f"{type(exc).__name__}: {str(exc)[:160]}"

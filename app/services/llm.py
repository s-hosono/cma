import json
import os
from typing import Optional, Dict, Any

_client = None
_provider = None  # "azure" or "openai"
_model = None     # OpenAI: model name, Azure: deployment name

# Tunables (env overridable)
DEFAULT_MAX_TOKENS = int(os.getenv("CMA_LLM_MAX_TOKENS", "1024"))
DEFAULT_TEMPERATURE = float(os.getenv("CMA_LLM_TEMPERATURE", "0.2"))
DEFAULT_JSON_ENFORCE = os.getenv("CMA_LLM_JSON_ENFORCE", "true").lower() in ("1", "true", "yes", "on")
DEFAULT_REASONING_EFFORT = os.getenv("CMA_LLM_REASONING_EFFORT", "medium")  # low|medium|high
DEFAULT_TIMEOUT = float(os.getenv("CMA_LLM_TIMEOUT_SEC", "30"))


def _ensure_client():
    """優先的にAzure OpenAIを使用し、未設定時はOpenAI互換APIを利用。
    Azure環境変数: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT
    OpenAI環境変数: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    """
    global _client, _provider, _model
    if _client is not None:
        return _client

    az_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    az_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    az_api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("AZURE_OPENAI_API_VER") or "2024-12-01-preview"
    az_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("OPENAI_MODEL") or "o1"

    if az_api_key and az_endpoint:
        try:
            from openai import AzureOpenAI
            _client = AzureOpenAI(azure_endpoint=az_endpoint, api_key=az_api_key, api_version=az_api_version)
            _provider = "azure"
            _model = az_deployment  # Azureはdeployment名をmodelに指定
            return _client
        except Exception:
            _client = None

    # フォールバック: 通常のOpenAI互換
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    _model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if api_key:
        try:
            from openai import OpenAI
            _client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            _provider = "openai"
            return _client
        except Exception:
            _client = None
    return None


def is_configured() -> bool:
    return _ensure_client() is not None


def chat(system: str, user: str, json_mode: bool = False, temperature: Optional[float] = None, max_tokens: Optional[int] = None, timeout: Optional[float] = None, reasoning_effort: Optional[str] = None) -> str:
    client = _ensure_client()
    if not client:
        raise RuntimeError("LLM client not configured")
    # Defaults
    if temperature is None:
        temperature = DEFAULT_TEMPERATURE
    if max_tokens is None:
        max_tokens = DEFAULT_MAX_TOKENS
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if reasoning_effort is None:
        reasoning_effort = DEFAULT_REASONING_EFFORT
    # Azure o1系はresponses APIを利用
    if _provider == "azure" and _model and str(_model).lower().startswith("o1"):
        # responses APIはinput文字列を受け付ける
        params: Dict[str, Any] = {
            "model": _model,
            "input": f"System: {system}\nUser: {user}",
            "max_output_tokens": max_tokens,
        }
        if json_mode and DEFAULT_JSON_ENFORCE:
            params["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            params["reasoning"] = {"effort": reasoning_effort}
        try:
            # timeout はwith_optionsで付与
            resp = client.with_options(timeout=timeout).responses.create(**params)
            # openai v1にはoutput_textのショートカットがある
            text = getattr(resp, "output_text", None)
            if text:
                return text
            # フォールバック: 最初のテキストを拾う
            out = getattr(resp, "output", None)
            if out and isinstance(out, list) and out:
                content = getattr(out[0], "content", None)
                if content and isinstance(content, list) and content:
                    txt = getattr(content[0], "text", None)
                    if txt and getattr(txt, "value", None):
                        return txt.value
            return ""
        except Exception:
            # 失敗時は従来のchat APIで試行（多くは失敗するが保険）
            pass

    # 通常のchat.completions API
    params: Dict[str, Any] = {
        "model": _model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if not (_model and str(_model).lower().startswith("o1")):
        params["temperature"] = temperature
    if json_mode and DEFAULT_JSON_ENFORCE:
        params["response_format"] = {"type": "json_object"}
    params["max_tokens"] = max_tokens
    resp = client.with_options(timeout=timeout).chat.completions.create(**params)
    return resp.choices[0].message.content or ""


def chat_json(system: str, user: str, temperature: Optional[float] = None, max_tokens: Optional[int] = None, timeout: Optional[float] = None, reasoning_effort: Optional[str] = None) -> Optional[dict]:
    try:
        text = chat(system, user, json_mode=True, temperature=temperature, max_tokens=max_tokens, timeout=timeout, reasoning_effort=reasoning_effort)
        return json.loads(text)
    except Exception:
        try:
            text = chat(system, user, json_mode=False, temperature=temperature, max_tokens=max_tokens, timeout=timeout, reasoning_effort=reasoning_effort)
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None

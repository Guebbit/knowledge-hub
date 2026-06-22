"""
LLM provider adapters.

call_llm() is the only public function — everything else is private (_underscore).
It dispatches to the right adapter via _ADAPTERS, a dict defined at the bottom of
this file. To add a new provider: write a _call_X function, add it to _ADAPTERS below.
Then use it via a preset in .env: PRESET_X=yourprovider:some-model

config.PROVIDER and config.MODEL are read at call time (not import time) so that
runtime overrides via --provider / --preset / --model take effect.
"""
import os

# Import the module object so runtime mutations to config.PROVIDER / config.MODEL are visible.
import config
from config import OLLAMA_URL, OLLAMA_NUM_CTX, OLLAMA_TIMEOUT  # these never change at runtime
from utils import die


def call_llm(prompt: str) -> str:
    """Dispatch the prompt to the configured provider and return the response."""
    adapter = _ADAPTERS.get(config.PROVIDER, _call_ollama)
    return adapter(prompt)


def _fallback_to_local(reason: str) -> bool:
    """Warn about a missing credential and offer to fall back to the local preset."""
    import sys
    fallback_provider, fallback_model = config.PRESETS.get("local", ("ollama", "qwen3:8b"))
    print(f"\nWarning  : {reason}")
    if not sys.stdin.isatty():
        # Non-interactive (piped / CI): auto-fall back without prompting.
        print(f"Auto     : falling back to {fallback_provider}:{fallback_model}")
        config.PROVIDER = fallback_provider
        config.MODEL = fallback_model
        return True
    try:
        answer = input(f"Use local fallback ({fallback_provider}:{fallback_model}) instead? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if answer in ("", "y", "yes"):
        config.PROVIDER = fallback_provider
        config.MODEL = fallback_model
        print(f"Switched : using {fallback_provider}:{fallback_model}")
        return True
    return False


# --- Adapters ----------------------------------------------------------------
# Leading underscore = private. Don't call these directly from other modules.
# Each does a lazy import — the provider's library is only loaded if actually used,
# so missing packages don't crash the script when using a different provider.

def _call_ollama(prompt: str) -> str:
    import requests
    try:
        # requests.post() sends an HTTP POST to the Ollama REST API.
        # json= serialises the dict to JSON and sets Content-Type: application/json automatically.
        res = requests.post(
            f"{OLLAMA_URL}/api/generate",  # native Ollama endpoint (NOT OpenAI-compatible)
            json={
                "model": config.MODEL,        # read at call time — reflects runtime overrides
                "prompt": prompt,
                "stream": False,              # wait for the full response, not token-by-token
                "options": {"num_ctx": OLLAMA_NUM_CTX},
            },
            timeout=OLLAMA_TIMEOUT,           # seconds before giving up (large models are slow)
        )
        # raise_for_status() does nothing on 2xx; raises requests.HTTPError on 4xx/5xx
        res.raise_for_status()
        # res.json() parses the JSON response body into a Python dict
        return res.json()["response"]
    except requests.exceptions.ConnectionError:
        die(f"Cannot reach Ollama at {OLLAMA_URL} — is 'docker compose up -d' running?")
    except requests.exceptions.HTTPError as e:
        die(f"Ollama returned HTTP {e.response.status_code}")


def _call_anthropic(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        die("anthropic package not installed — run: pip install anthropic")

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        if _fallback_to_local("ANTHROPIC_API_KEY not set — add it to .env"):
            return _call_ollama(prompt)
        die("ANTHROPIC_API_KEY not set — add it to .env")

    # anthropic.Anthropic() creates a stateless API client; the key is sent as a header on each request
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=config.MODEL,
        max_tokens=4096,      # hard cap on response length in tokens (1 token ≈ 0.75 words)
        messages=[{"role": "user", "content": prompt}],
    )
    # .content is a list of content blocks (text, images, tool calls...) — [0] is always the text reply
    return msg.content[0].text


def _call_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        die("openai package not installed — run: pip install openai")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        if _fallback_to_local("OPENAI_API_KEY not set — add it to .env"):
            return _call_ollama(prompt)
        die("OPENAI_API_KEY not set — add it to .env")

    # base_url lets the OpenAI client talk to any OpenAI-compatible server, not just api.openai.com
    # (e.g. GitHub Models, Azure OpenAI, vLLM, LM Studio)
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    client = OpenAI(api_key=key, base_url=base_url)
    res = client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    # .choices is a list of candidate completions (usually 1); [0] is the first/only one
    return res.choices[0].message.content


# Dispatch table — maps provider names to their adapter functions.
# Defined here (after the functions) so all names are already in scope.
# Add a new provider by adding one line here + a _call_X function above.
_ADAPTERS: dict[str, object] = {
    "ollama":    _call_ollama,
    "anthropic": _call_anthropic,
    "openai":    _call_openai,
}

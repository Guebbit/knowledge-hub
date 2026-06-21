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
    # _ADAPTERS.get() looks up the function for the current provider.
    # Falls back to _call_ollama if the provider name is unrecognised.
    adapter = _ADAPTERS.get(config.PROVIDER, _call_ollama)
    return adapter(prompt)


# --- Adapters ----------------------------------------------------------------
# Leading underscore = private. Don't call these directly from other modules.
# Each does a lazy import — the provider's library is only loaded if actually used,
# so missing packages don't crash the script when using a different provider.

def _call_ollama(prompt: str) -> str:
    import requests
    try:
        res = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": config.MODEL,        # read at call time — reflects runtime overrides
                "prompt": prompt,
                "stream": False,              # wait for the full response, not token-by-token
                "options": {"num_ctx": OLLAMA_NUM_CTX},
            },
            timeout=OLLAMA_TIMEOUT,
        )
        res.raise_for_status()                # raises exception on HTTP 4xx / 5xx
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
        die("ANTHROPIC_API_KEY not set — add it to .env")

    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=config.MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    # .content is a list of blocks — [0] is always the text reply
    return msg.content[0].text


def _call_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        die("openai package not installed — run: pip install openai")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        die("OPENAI_API_KEY not set — add it to .env")

    client = OpenAI(api_key=key)
    res = client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    # .choices is a list of completions — [0] is the first (and only) one
    return res.choices[0].message.content


# Dispatch table — maps provider names to their adapter functions.
# Defined here (after the functions) so all names are already in scope.
# Add a new provider by adding one line here + a _call_X function above.
_ADAPTERS: dict[str, object] = {
    "ollama":    _call_ollama,
    "anthropic": _call_anthropic,
    "openai":    _call_openai,
}

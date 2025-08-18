# app/nlp/openai_client.py
import httpx
from openai import OpenAI
from ..config import Settings

# httpx.Client sem proxies (evita erro "proxies" nas versões novas)
_http_client = httpx.Client(timeout=30.0)

client = OpenAI(
    api_key=Settings.OPENAI_API_KEY,
    http_client=_http_client
)

def chat(messages, model=None, **kwargs):
    """
    Wrapper para chat.completions.create (OpenAI SDK >= 1.x).
    """
    model = model or (Settings.OPENAI_MODEL or "gpt-4o-mini")
    temperature = kwargs.get("temperature", 0)
    return client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

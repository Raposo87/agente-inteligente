# app/nlp/openai_client.py
from openai import OpenAI
from ..config import Settings

# NADA de proxies aqui. Se um dia precisares de proxy:
# import httpx; httpx_client = httpx.Client(proxies="http://host:8080", timeout=30)
# client = OpenAI(api_key=Settings.OPENAI_API_KEY, http_client=httpx_client)

client = OpenAI(api_key=Settings.OPENAI_API_KEY)

def chat(messages, model=None, **kwargs):
    """
    Wrapper simples para chat.completions.create.
    Mantém temperature=0 por defeito e permite override via kwargs.
    """
    model = model or (Settings.OPENAI_MODEL or "gpt-4o-mini")
    temperature = kwargs.get("temperature", 0)
    return client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

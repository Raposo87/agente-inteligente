# app/nlp/openai_client.py
from openai import OpenAI
from ..config import Settings

# Usa a SDK nova da OpenAI (>=1.x)
# NADA de 'proxies' no __init__, para evitar o erro que viste.
client = OpenAI(api_key=Settings.OPENAI_API_KEY)

def chat(messages, model=None, temperature=0.2, max_tokens=400):
    """
    messages: [{"role":"system"/"user"/"assistant", "content":"..."}]
    """
    mdl = model or (Settings.OPENAI_MODEL or "gpt-4o-mini")  # escolhe o teu default
    return client.chat.completions.create(
        model=mdl,
        messages=messages,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
    )

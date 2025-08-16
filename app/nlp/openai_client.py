import os
import openai
from ..config import Settings

openai.api_key = Settings.OPENAI_API_KEY

def chat(messages, model=None, response_format=None):
    model = model or Settings.OPENAI_MODEL
    return openai.chat.completions.create(
        model=model,
        messages=messages,
        response_format=response_format or {"type":"json_object"}
    )
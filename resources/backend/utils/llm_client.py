import httpx
from config.settings import settings

class LLMClient:
    def __init__(self, provider=None, api_key=None, model_tier="balanced"):
        self.provider = provider or "gemini"
        self.api_key = api_key or settings.gemini_api_key
        self.model_tier = model_tier
        self.models = {
            "openai":    {"fast": "gpt-4.1-nano", "balanced": "gpt-4.1-mini", "best": "gpt-4.1"},
            "gemini":    {"fast": "gemini-2.5-flash-lite", "balanced": "gemini-2.5-flash", "best": "gemini-2.5-pro"},
            "anthropic": {"fast": "claude-haiku-4-5-20251001", "balanced": "claude-sonnet-4-6", "best": "claude-opus-4-7"}
        }

    def get_model(self):
        return self.models.get(self.provider, {}).get(self.model_tier, "gemini-2.5-flash")

    async def complete(self, prompt, max_tokens=1000):
        if self.provider == "gemini":
            return await self._gemini(prompt, max_tokens)
        elif self.provider == "openai":
            return await self._openai(prompt, max_tokens)
        elif self.provider == "anthropic":
            return await self._anthropic(prompt, max_tokens)
        raise ValueError(f"Unknown provider: {self.provider}")

    async def _gemini(self, prompt, max_tokens):
        model = self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens}}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def _openai(self, prompt, max_tokens):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.get_model(), "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def _anthropic(self, prompt, max_tokens):
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {"model": self.get_model(), "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["content"][0]["text"]

def get_llm_client(provider=None, api_key=None, model_tier="balanced"):
    return LLMClient(provider=provider, api_key=api_key, model_tier=model_tier)

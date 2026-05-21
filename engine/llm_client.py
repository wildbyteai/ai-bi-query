import config


class LLMClient:
    """LLM 抽象层。"""

    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class ClaudeClient(LLMClient):
    def __init__(self):
        import anthropic
        kwargs = {"api_key": config.ANTHROPIC_API_KEY}
        if config.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = config.ANTHROPIC_BASE_URL
        self.client = anthropic.Anthropic(**kwargs)

    def generate(self, prompt: str) -> str:
        resp = self.client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        texts = []
        for block in resp.content:
            if hasattr(block, "text") and block.text:
                texts.append(block.text)
        return "\n".join(texts) if texts else ""


class QwenClient(LLMClient):
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=config.DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def generate(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        return resp.choices[0].message.content


class DeepSeekClient(LLMClient):
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )

    def generate(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        return resp.choices[0].message.content


def get_client() -> LLMClient:
    providers = {
        "claude": ClaudeClient,
        "qwen": QwenClient,
        "deepseek": DeepSeekClient,
    }
    cls = providers.get(config.LLM_PROVIDER)
    if not cls:
        raise ValueError(f"不支持的 LLM: {config.LLM_PROVIDER}")
    return cls()

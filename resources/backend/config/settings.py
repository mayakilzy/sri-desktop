from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Smart Review Intelligence"
    debug: bool = True
    database_url: str = "sqlite:////root/data/sri/databases/sri.db"

    # LLM Settings
    llm_provider: str = "gemini"
    llm_model_tier: str = "balanced"

    # API Keys
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    app_secret_key: str = "dev-secret"
    log_level: str = "INFO"
    log_dir: str = "/root/data/sri/logs"

    class Config:
        env_file = "/root/apps/services/fastapi/app/sri/.env"

settings = Settings()

# نضيف للـ .env

"""Small, environment-backed settings for the FilingScope data pipeline."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    data_raw_dir: Path = Path("data/raw")
    data_processed_dir: Path = Path("data/processed")
    sec_user_agent: str = ""

    qdrant_mode: Literal["local", "cloud"] = "local"
    qdrant_local_path: Path = Path("data/processed/qdrant")
    qdrant_index_manifest_path: Path = Path(
        "data/processed/qdrant_index_manifest.json"
    )
    qdrant_cloud_url: str = ""
    qdrant_cloud_api_key: SecretStr = SecretStr("")

    embedding_model_id: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_model_revision: str = "e9b6763023c676ca8431644204f50c2b100d9aab"
    reranker_model_id: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_model_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    embedding_generations_dir: Path = Path("data/embedding_generations")
    embedding_generation_path: Path | None = None

    @model_validator(mode="after")
    def validate_qdrant_cloud_settings(self) -> "Settings":
        if self.qdrant_mode == "cloud":
            if not self.qdrant_cloud_url or not self.qdrant_cloud_api_key.get_secret_value():
                raise ValueError(
                    "QDRANT_CLOUD_URL and QDRANT_CLOUD_API_KEY are required in cloud mode"
                )
        return self


settings = Settings()

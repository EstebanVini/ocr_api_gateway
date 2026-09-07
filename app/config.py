from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.database import DEFAULT_DB_PATH


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ocr_space_api_key: str = Field(..., alias="OCR_SPACE_API_KEY", min_length=1)
    ocr_space_endpoint: str = Field("https://api.ocr.space/parse/image", alias="OCR_SPACE_ENDPOINT")
    ocr_max_upload_bytes: int = Field(1_048_576, alias="OCR_MAX_UPLOAD_BYTES", gt=0)
    ocr_max_pdf_pages: int = Field(3, alias="OCR_MAX_PDF_PAGES", gt=0)
    ocr_timeout_seconds: float = Field(120.0, alias="OCR_TIMEOUT_SECONDS", gt=0)
    ocr_min_jpeg_quality: int = Field(40, alias="OCR_MIN_JPEG_QUALITY", ge=1, le=95)
    ocr_min_pdf_dpi: int = Field(150, alias="OCR_MIN_PDF_DPI", ge=150)
    ocr_default_language: str = Field("spa", alias="OCR_DEFAULT_LANGUAGE")
    ocr_default_engine: int = Field(2, alias="OCR_DEFAULT_ENGINE")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    ocr_max_input_bytes: int = Field(20_971_520, alias="OCR_MAX_INPUT_BYTES", gt=0)
    ocr_min_image_longest_side_px: int = Field(1500, alias="OCR_MIN_IMAGE_LONGEST_SIDE_PX", gt=0)
    ocr_min_image_scale_factor: float = Field(0.5, alias="OCR_MIN_IMAGE_SCALE_FACTOR", gt=0, le=1)
    ocr_max_retries: int = Field(2, alias="OCR_MAX_RETRIES", ge=0)

    api_keys_db_path: str = Field(DEFAULT_DB_PATH, alias="API_KEYS_DB_PATH")
    rate_limit_requests: int = Field(30, alias="RATE_LIMIT_REQUESTS", gt=0)
    rate_limit_window_seconds: float = Field(60.0, alias="RATE_LIMIT_WINDOW_SECONDS", gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()

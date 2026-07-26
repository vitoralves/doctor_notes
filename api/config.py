import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")
except ImportError:
    pass

DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "consultation-app")
S3_EXPORTS_BUCKET = os.getenv("S3_EXPORTS_BUCKET", "consultation-app-exports-890886303710")
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-west-2"))
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
RATE_LIMIT_PER_DAY = int(os.getenv("RATE_LIMIT_PER_DAY", "20"))
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5-nano")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
PRESIGNED_URL_EXPIRES = int(os.getenv("PRESIGNED_URL_EXPIRES", "3600"))

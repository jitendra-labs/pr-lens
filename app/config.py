from dotenv import load_dotenv
import os

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
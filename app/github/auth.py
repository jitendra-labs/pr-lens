import jwt
import time

from app.config import GITHUB_APP_ID

PRIVATE_KEY_PATH = 'keys/prlens.private-key.pem'

def generate_jwt():
    with open(PRIVATE_KEY_PATH, 'r') as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        # Subtract 60 seconds to safeguard against slight clock variations
        'iat': now - 60,
        # Max validity allowed by GitHub is 10 minutes (600 seconds)
        'exp': now + 540, 
        'iss': str(GITHUB_APP_ID)
    }

    return jwt.encode(
        payload,
        private_key,
        algorithm='RS256'
    )
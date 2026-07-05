import requests
import os
import logging
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(env_path)

logger = logging.getLogger(__name__)

API_VERSION = os.getenv('META_API_VERSION', 'v22.0')
REQUEST_TIMEOUT = int(os.getenv('META_REQUEST_TIMEOUT', '30'))


def _strip_phone(p):
    return p.replace('+', '').replace(' ', '').replace('-', '')


def fetch_phone_number_id(waba_id, phone_number):
    token = os.getenv('META_ACCESS_TOKEN')
    if not token or not waba_id:
        return None

    url = f'https://graph.facebook.com/{API_VERSION}/{waba_id}/phone_numbers'
    headers = {'Authorization': f'Bearer {token}'}

    clean = _strip_phone(phone_number)

    try:
        res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        data = res.json()
        for pn in data.get('data', []):
            pn_clean = _strip_phone(pn.get('display_phone_number', ''))
            if pn_clean == clean:
                return pn['id']
        return None
    except Exception as e:
        logger.warning(f"fetch_phone_number_id failed for waba={waba_id}: {e}")
        return None

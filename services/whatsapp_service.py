import requests
from dotenv import load_dotenv
from pathlib import Path
import os
import logging

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(env_path)

logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN')
FALLBACK_PHONE_NUMBER_ID = os.getenv('META_PHONE_NUMBER_ID')
API_VERSION = os.getenv('META_API_VERSION', 'v22.0')
REQUEST_TIMEOUT = int(os.getenv('META_REQUEST_TIMEOUT', '30'))


def _get_headers():
    return {
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Content-Type': 'application/json',
    }


def _get_api_url(phone_number_id=None):
    pid = phone_number_id or FALLBACK_PHONE_NUMBER_ID
    if not pid:
        logger.error("No phone_number_id available for WhatsApp API call")
        return None
    return f'https://graph.facebook.com/{API_VERSION}/{pid}/messages'


def _clean_phone(phone):
    if phone.startswith('whatsapp:'):
        phone = phone.replace('whatsapp:', '')
    return phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')


def _is_success(res, data):
    if not res.ok:
        return False
    if data.get('error'):
        return False
    return True


def send_text_message(phone, message, phone_number_id=None):
    to = _clean_phone(phone)
    url = _get_api_url(phone_number_id)
    if not url:
        return {"status": "failed", "error": "No phone_number_id configured"}

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'text',
        'text': {'preview_url': False, 'body': message},
    }

    try:
        res = requests.post(url, json=payload, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        data = res.json()
        msg_id = data.get('messages', [{}])[0].get('id', '')
        return {"status": "success" if _is_success(res, data) else "failed", "message_id": msg_id, "response": data}
    except Exception as e:
        logger.error(f"send_text_message failed: {e}")
        return {"status": "failed", "error": str(e)}


def send_template_message(phone, template_name, params, phone_number_id=None, language='en'):
    to = _clean_phone(phone)
    url = _get_api_url(phone_number_id)
    if not url:
        return {"status": "failed", "error": "No phone_number_id configured"}

    components = [{
        'type': 'body',
        'parameters': [{'type': 'text', 'text': p} for p in params],
    }]

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': language},
            'components': components,
        },
    }

    try:
        res = requests.post(url, json=payload, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        data = res.json()
        msg_id = data.get('messages', [{}])[0].get('id', '')
        return {"status": "success" if _is_success(res, data) else "failed", "message_id": msg_id, "response": data}
    except Exception as e:
        logger.error(f"send_template_message failed: {e}")
        return {"status": "failed", "error": str(e)}


def send_read_and_typing(phone, message_id, phone_number_id=None):
    url = _get_api_url(phone_number_id)
    if not url:
        return

    payload = {
        'messaging_product': 'whatsapp',
        'status': 'read',
        'message_id': message_id,
        'typing_indicator': {'type': 'text'},
    }
    try:
        requests.post(url, json=payload, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
    except Exception as e:
        logger.warning(f"send_read_and_typing failed: {e}")


def mark_message_read(message_id, phone_number_id=None):
    url = _get_api_url(phone_number_id)
    if not url:
        return

    payload = {
        'messaging_product': 'whatsapp',
        'status': 'read',
        'message_id': message_id,
    }
    try:
        requests.post(url, json=payload, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
    except Exception as e:
        logger.warning(f"mark_message_read failed: {e}")

import threading
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
import os
import logging

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(env_path)

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv('VITE_SUPABASE_URL')
SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
ANON_KEY = os.getenv('VITE_SUPABASE_ANON_KEY')

_lock = threading.Lock()
_supabase = None


def get_supabase():
    global _supabase
    if _supabase is not None:
        return _supabase
    with _lock:
        if _supabase is not None:
            return _supabase
        if not SERVICE_KEY:
            logger.warning("SUPABASE_SERVICE_KEY not set — falling back to ANON_KEY. Admin operations will fail.")
        key = SERVICE_KEY or ANON_KEY
        _supabase = create_client(SUPABASE_URL, key)
    return _supabase

from database.supabase_client import get_supabase

supabase = get_supabase()


def get_db():
    return supabase

import os
import logging
from datetime import date, datetime, timedelta, timezone
from database.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TZ_OFFSET = os.getenv('TIMEZONE_OFFSET', '+05:30')
_tz_parts = _TZ_OFFSET.split(':')
_tz_hours = int(_tz_parts[0])
_tz_mins = int(_tz_parts[1]) if len(_tz_parts) > 1 else 0
TZ_DELTA = timedelta(hours=_tz_hours, minutes=_tz_mins)

TRIGGERS = [(1, 0), (3, 1), (15, 3), (30, 15)]


def _today_local() -> date:
    return (datetime.now(timezone.utc) + TZ_DELTA).date()


def _local_midnight_utc(days_offset=0):
    local_today = _today_local()
    target = local_today + timedelta(days=days_offset)
    local_midnight = datetime.combine(target, datetime.min.time())
    return (local_midnight - TZ_DELTA).replace(tzinfo=timezone.utc)


def get_customers_due_today():
    supabase = get_supabase()
    today = _today_local()
    due = []

    for trigger_day, prev_seq in TRIGGERS:
        target_date = (today - timedelta(days=trigger_day)).isoformat()
        try:
            batch = supabase.table('customers').select('*').eq(
                'status', 'active'
            ).eq(
                'current_sequence_day', prev_seq
            ).eq(
                'purchase_date', target_date
            ).execute()
            for c in batch.data:
                due.append((c, trigger_day))
        except Exception as e:
            logger.error(f"get_customers_due_today (trigger={trigger_day}): {e}")

    logger.info(f"get_customers_due_today: {len(due)} due")
    return due


def get_customers_with_appointment_today():
    supabase = get_supabase()
    start = _local_midnight_utc(0)
    end = _local_midnight_utc(1)

    try:
        customers = supabase.table('customers').select('*').gte(
            'next_booking', start.isoformat()
        ).lt('next_booking', end.isoformat()).execute()
        logger.info(f"get_customers_with_appointment_today: {len(customers.data)}")
        return [(c, 'appointment_reminder') for c in customers.data]
    except Exception as e:
        logger.error(f"get_customers_with_appointment_today: {e}")
        return []


def get_customers_with_past_appointment():
    supabase = get_supabase()
    start = _local_midnight_utc(-1)
    end = _local_midnight_utc(0)

    try:
        customers = supabase.table('customers').select('*').gte(
            'next_booking', start.isoformat()
        ).lt('next_booking', end.isoformat()).execute()
        logger.info(f"get_customers_with_past_appointment: {len(customers.data)}")
        return [(c, 'appointment_followup') for c in customers.data]
    except Exception as e:
        logger.error(f"get_customers_with_past_appointment: {e}")
        return []


def get_next_sequence_day(current_day):
    next_days = {0: 1, 1: 3, 3: 15, 15: 30}
    return next_days.get(current_day, 'completed')


def get_template_name_for_day(sequence_day):
    templates = {0: 'vi_day1_welcome', 1: 'vi_day3_checkin',
                 3: 'vi_day15_followup', 15: 'vi_day30_upsell'}
    return templates.get(sequence_day)

import os
import random
from datetime import date, datetime, timedelta, timezone
from database.supabase_client import get_supabase
import logging

logger = logging.getLogger(__name__)

TOUCH_COUNT = 4

_TZ_OFFSET = os.getenv('TIMEZONE_OFFSET', '+05:30')
_tz_parts = _TZ_OFFSET.split(':')
_tz_hours = int(_tz_parts[0])
_tz_mins = int(_tz_parts[1]) if len(_tz_parts) > 1 else 0
TZ_DELTA = timedelta(hours=_tz_hours, minutes=_tz_mins)


def _today_local() -> date:
    return (datetime.now(timezone.utc) + TZ_DELTA).date()


def insert_welcome_touch(customer, business):
    supabase = get_supabase()
    customer_id = customer.get('id')
    business_id = business.get('id')
    if not customer_id or not business_id:
        logger.error(f"insert_welcome_touch: missing customer_id or business_id")
        return None

    row = {
        'customer_id': customer_id,
        'business_id': business_id,
        'touch_number': 1,
        'scheduled_date': _today_local().isoformat(),
        'status': 'completed',
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }
    result = supabase.table('follow_up_sequences').insert(row).execute()
    return result.data[0] if result.data else None


def generate_followup_sequence(customer, business, agent, start_touch=1):
    supabase = get_supabase()
    customer_id = customer.get('id')
    business_id = business.get('id')
    if not customer_id or not business_id:
        return []

    existing = supabase.table('follow_up_sequences').select('id').eq(
        'customer_id', customer_id
    ).eq('status', 'pending').execute()
    if existing.data:
        return existing.data

    purchase_date = customer.get('purchase_date')
    if not purchase_date:
        return []

    if isinstance(purchase_date, str):
        pd = date.fromisoformat(purchase_date)
    else:
        pd = purchase_date

    today = _today_local()
    start_offset = 2
    end_offset = 30
    available_days = list(range(start_offset, end_offset + 1))

    if len(available_days) < TOUCH_COUNT:
        chosen = available_days
    else:
        chosen = sorted(random.sample(available_days, TOUCH_COUNT))

    rows = []
    for i, day_offset in enumerate(chosen):
        sched_date = pd + timedelta(days=day_offset)
        if sched_date < today:
            continue
        rows.append({
            'customer_id': customer_id,
            'business_id': business_id,
            'touch_number': start_touch + i,
            'scheduled_date': sched_date.isoformat(),
            'status': 'pending',
        })

    if rows:
        result = supabase.table('follow_up_sequences').insert(rows).execute()
        return result.data

    return []


def get_due_followups(scheduled_date=None):
    supabase = get_supabase()
    if scheduled_date is None:
        scheduled_date = _today_local()
    elif isinstance(scheduled_date, datetime):
        scheduled_date = scheduled_date.date()

    result = supabase.table('follow_up_sequences').select(
        '*, customers!inner(*)'
    ).eq('status', 'pending').lte('scheduled_date', scheduled_date.isoformat()).execute()

    due = []
    for row in result.data:
        customer = row.get('customers')
        if customer and customer.get('status') == 'active':
            due.append((customer, row.get('touch_number'), row.get('id')))
    return due


def complete_followup(sequence_id):
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    supabase.table('follow_up_sequences').update({
        'status': 'completed',
        'completed_at': now,
    }).eq('id', sequence_id).execute()

    row = supabase.table('follow_up_sequences').select('customer_id, touch_number').eq('id', sequence_id).execute()
    if row.data:
        customer_id = row.data[0].get('customer_id')
        touch = row.data[0].get('touch_number')
        if not customer_id:
            return
        remaining = supabase.table('follow_up_sequences').select('id').eq(
            'customer_id', customer_id
        ).eq('status', 'pending').execute()
        if not remaining.data:
            supabase.table('customers').update({
                'status': 'completed',
                'current_sequence_day': 30,
            }).eq('id', customer_id).execute()
        else:
            supabase.table('customers').update({
                'current_sequence_day': touch,
            }).eq('id', customer_id).execute()

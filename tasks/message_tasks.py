import os
from celery_app import celery_app
from database.supabase_client import get_supabase
from services.message_pipeline import enqueue, process_batch, retry_failed
from services.scheduler_service import (
    get_customers_with_appointment_today,
    get_customers_with_past_appointment,
)
from services.followup_service import get_due_followups
from datetime import datetime, timedelta, timezone
from collections import Counter
import random
import logging

logger = logging.getLogger(__name__)

_TZ_OFFSET = os.getenv('TIMEZONE_OFFSET', '+05:30')
_tz_parts = _TZ_OFFSET.split(':')
_tz_hours = int(_tz_parts[0])
_tz_mins = int(_tz_parts[1]) if len(_tz_parts) > 1 else 0
TZ_DELTA = timedelta(hours=_tz_hours, minutes=_tz_mins)


def _fetch_biz_map(supabase, customers):
    biz_ids = list(set(c.get('business_id') for c in customers if c.get('business_id')))
    if not biz_ids:
        return {}
    biz_result = supabase.table('business_profiles').select('id,name,*').in_('id', biz_ids).execute()
    return {b['id']: b for b in (biz_result.data or [])}


def _enqueue_customers(supabase, items, biz_map, message_type, key_fn):
    count = 0
    for customer, extra in items:
        try:
            biz_id = customer.get('business_id')
            if not biz_id or biz_id not in biz_map:
                continue
            touch_number, seq_id = key_fn(extra) if key_fn else (None, None)
            optimal_time = _get_optimal_time(customer)
            enqueue(customer, biz_map[biz_id], message_type, touch_number, optimal_time, followup_sequence_id=seq_id)
            count += 1
        except Exception as e:
            logger.error(f"Failed to enqueue {message_type} for {customer.get('id')}: {e}")
    return count


@celery_app.task
def enqueue_daily_sequences():
    supabase = get_supabase()

    due_followups = get_due_followups()
    reminders = get_customers_with_appointment_today()
    followups = get_customers_with_past_appointment()

    all_customers = (
        [c for c, _, _ in due_followups]
        + [c for c, _ in reminders]
        + [c for c, _ in followups]
    )
    biz_map = _fetch_biz_map(supabase, all_customers)

    seq_count = _enqueue_customers(
        supabase, [(c, (t, s)) for c, t, s in due_followups], biz_map, 'sequence',
        lambda x: x,
    )
    rem_count = _enqueue_customers(
        supabase, reminders, biz_map, 'appointment_reminder', lambda x: (None, None),
    )
    fup_count = _enqueue_customers(
        supabase, followups, biz_map, 'appointment_followup', lambda x: (None, None),
    )

    logger.info(f"Enqueued {seq_count} sequences, {rem_count} reminders, {fup_count} followups")
    return {'sequences': seq_count, 'reminders': rem_count, 'followups': fup_count}


@celery_app.task
def process_pipeline_batch():
    processed = process_batch(batch_size=20)
    logger.info(f"Pipeline batch processed {processed} items")
    return {'processed': processed}


@celery_app.task
def retry_failed_pipeline():
    result = retry_failed()
    logger.info(f"Pipeline retry: {result['retried']} retried, {result['dead']} dead")
    return result


@celery_app.task
def process_smart_timing():
    supabase = get_supabase()
    try:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc + TZ_DELTA
        week_ago_local = now_local - timedelta(days=7)

        customers = supabase.table('customers').select('id').gte(
            'response_count', 3
        ).eq('status', 'active').execute()

        if not customers.data:
            logger.info("Smart timing: no customers with response_count >= 3")
            return {'updated': 0}

        customer_ids = [c['id'] for c in customers.data]
        all_msgs = supabase.table('messages').select('customer_id,timestamp').eq(
            'direction', 'received'
        ).in_('customer_id', customer_ids).execute()

        msgs_by_customer = {}
        for msg in (all_msgs.data or []):
            cid = msg.get('customer_id')
            if cid:
                msgs_by_customer.setdefault(cid, []).append(msg)

        updated = 0
        for customer in customers.data:
            cid = customer['id']
            msgs = msgs_by_customer.get(cid, [])
            if len(msgs) < 3:
                continue

            recent = []
            older = []
            for m in msgs:
                ts_raw = m.get('timestamp')
                if not ts_raw:
                    continue
                if isinstance(ts_raw, str):
                    ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
                else:
                    ts = ts_raw
                ts_local = ts + TZ_DELTA
                hour = ts_local.hour
                if ts_local >= week_ago_local:
                    recent.append(hour)
                else:
                    older.append(hour)

            all_hours = recent + older
            if not all_hours:
                continue

            if recent:
                weights = [3] * len(recent) + [1] * len(older)
                weighted = []
                for h, w in zip(all_hours, weights):
                    weighted.extend([h] * w)
                best_hour = Counter(weighted).most_common(1)[0][0]
            else:
                best_hour = Counter(all_hours).most_common(1)[0][0]

            supabase.table('customers').update({
                'best_contact_time': f"{best_hour:02d}:00"
            }).eq('id', cid).execute()
            updated += 1

        logger.info(f"Smart timing updated for {updated} customers")
        return {'updated': updated}
    except Exception as e:
        logger.error(f"Smart timing error: {e}")
        return {'updated': 0}


def _get_optimal_time(customer):
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc + TZ_DELTA
    today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    bct = customer.get('best_contact_time')
    if bct:
        try:
            hour, _ = bct.split(':')
            minute = random.randint(0, 59)
            local_dt = today_local.replace(hour=int(hour), minute=minute)
            return (local_dt - TZ_DELTA).isoformat()
        except (ValueError, TypeError):
            pass

    minute = random.randint(0, 59)
    local_dt = today_local.replace(hour=10, minute=minute)
    return (local_dt - TZ_DELTA).isoformat()

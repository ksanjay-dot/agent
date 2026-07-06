from database.supabase_client import get_supabase
from services.whatsapp_service import send_text_message, send_template_message
from services.deepseek_service import generate_followup_message, generate_appointment_message
from database.seed import get_active_agent
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time
import random

logger = logging.getLogger(__name__)

STAGES = [
    'pending_schedule',
    'pending_ai_gen',
    'ready_to_send',
    'sending',
    'sent',
    'failed',
    'dead',
]

SEND_WORKERS = 3
AI_WORKERS = 2
RATE_LIMIT_DELAY = 0.2


def enqueue(customer, business, message_type, sequence_day=None, scheduled_at=None, followup_sequence_id=None):
    supabase = get_supabase()
    if scheduled_at is None:
        scheduled_at = datetime.now(timezone.utc).isoformat()
    elif isinstance(scheduled_at, datetime):
        scheduled_at = scheduled_at.isoformat()

    row = {
        'customer_id': customer.get('id'),
        'business_id': business.get('id'),
        'message_type': message_type,
        'stage': 'pending_schedule',
        'sequence_day': sequence_day,
        'scheduled_at': scheduled_at,
        'payload': {
            'customer_name': customer.get('name'),
            'customer_phone': customer.get('phone'),
            'product': customer.get('product') or customer.get('product_purchased', ''),
            'purchase_date': str(customer.get('purchase_date', '')),
            'followup_sequence_id': followup_sequence_id,
        },
    }
    if not row['customer_id'] or not row['business_id']:
        logger.error(f"enqueue: missing customer_id or business_id — customer={customer.get('id')}, business={business.get('id')}")
        return None
    result = supabase.table('message_queue').insert(row).execute()
    return result.data[0] if result.data else None


def advance(queue_id, next_stage, updates=None, expected_stage=None):
    supabase = get_supabase()
    payload = {
        'stage': next_stage,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        **(updates or {}),
    }
    query = supabase.table('message_queue').update(payload).eq('id', queue_id)
    if expected_stage:
        query = query.eq('stage', expected_stage)
    result = query.execute()
    return len(result.data or []) > 0


def _fetch_pn_id_map(supabase, items):
    biz_ids = list(set(item.get('business_id') for item in items if item.get('business_id')))
    if not biz_ids:
        return {}
    biz_profiles = supabase.table('business_profiles').select('id, meta_phone_number_id').in_('id', biz_ids).execute()
    return {b['id']: b.get('meta_phone_number_id') for b in (biz_profiles.data or [])}


TEMPLATE_NAMES = ['follow_up']


def _send_item(item, pn_id):
    supabase = get_supabase()
    try:
        if not advance(item['id'], 'sending', expected_stage='ready_to_send'):
            logger.info(f"_send_item: {item['id']} already claimed by another worker")
            return 0

        phone = item.get('payload', {}).get('customer_phone', '')
        if not phone or not isinstance(phone, str) or len(phone) < 5:
            _handle_failure(item, f'Invalid phone: {phone}')
            return 0

        text = item.get('ai_generated_text', '')

        sent_template = False
        for attempt in range(2):
            cname = item.get('payload', {}).get('customer_name', 'there')
            cprod = item.get('payload', {}).get('product', 'your visit')
            tmpl_result = send_template_message(phone, TEMPLATE_NAMES[0], [cname, cprod], phone_number_id=pn_id, language='en')
            if tmpl_result.get('status') == 'success':
                sent_template = True
                break
            logger.warning(f"welcome_trigger attempt {attempt+1} failed for {phone}: {tmpl_result.get('error', 'unknown')}")
            time.sleep(1)

        if not sent_template:
            logger.warning(f"welcome_trigger failed after 2 attempts for {phone} — sending AI text only")

        time.sleep(random.uniform(8, 15))

        result = send_text_message(phone, text, phone_number_id=pn_id)
        if result.get('status') == 'success':
            msg_id = result.get('message_id', '')
            advance(item['id'], 'sent', {
                'meta_message_id': msg_id,
                'sent_at': datetime.now(timezone.utc).isoformat(),
            }, expected_stage='sending')
            item['meta_message_id'] = msg_id
            _update_customer_after_send(item)
        else:
            _handle_failure(item, result.get('error', 'Text send failed'))
    except Exception as e:
        _handle_failure(item, str(e))
    return 1


def _generate_ai_text(item):
    supabase = get_supabase()
    try:
        customer_data = supabase.table('customers').select('*').eq('id', item['customer_id']).execute()
        biz_data = supabase.table('business_profiles').select('*').eq('id', item['business_id']).execute()
        agent = get_active_agent(item['business_id'])

        if not customer_data.data or not biz_data.data or not agent:
            _handle_failure(item, 'Missing customer/business/agent')
            return 0

        customer = customer_data.data[0]
        business = biz_data.data[0]

        if item['message_type'] == 'sequence':
            text = generate_followup_message(customer, business, agent, item['sequence_day'])
        elif item['message_type'] in ('appointment_reminder', 'appointment_followup'):
            sub_type = 'reminder' if item['message_type'] == 'appointment_reminder' else 'followup'
            text = generate_appointment_message(customer, business, agent, sub_type)
        else:
            _handle_failure(item, f'Unknown message_type: {item["message_type"]}')
            return 0

        advance(item['id'], 'ready_to_send', {'ai_generated_text': text}, expected_stage='pending_ai_gen')
        return 1
    except Exception as e:
        _handle_failure(item, str(e))
        return 0


def process_batch(batch_size=20):
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    processed = 0

    schedule_items = supabase.table('message_queue').select('*').eq(
        'stage', 'pending_schedule'
    ).lte('scheduled_at', now).limit(batch_size).execute()

    for item in schedule_items.data:
        if advance(item['id'], 'pending_ai_gen', expected_stage='pending_schedule'):
            processed += 1

    ai_items = supabase.table('message_queue').select('*').eq(
        'stage', 'pending_ai_gen'
    ).limit(batch_size).execute()

    if ai_items.data:
        with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
            futures = [pool.submit(_generate_ai_text, item) for item in ai_items.data]
            for f in as_completed(futures):
                processed += f.result()

    ready_items = supabase.table('message_queue').select('*').eq(
        'stage', 'ready_to_send'
    ).lte('scheduled_at', now).limit(batch_size).execute()

    if ready_items.data:
        pn_map = _fetch_pn_id_map(supabase, ready_items.data)
        with ThreadPoolExecutor(max_workers=SEND_WORKERS) as pool:
            futures = []
            for item in ready_items.data:
                pn_id = pn_map.get(item.get('business_id'))
                futures.append(pool.submit(_send_item, item, pn_id))
                time.sleep(RATE_LIMIT_DELAY)
            for f in as_completed(futures):
                processed += f.result()

    return processed


def retry_failed():
    supabase = get_supabase()
    failed = supabase.table('message_queue').select('*').eq('stage', 'failed').limit(200).execute()

    retried = 0
    dead = 0
    for item in (failed.data or []):
        current_retry = item.get('retry_count') or 0
        max_r = item.get('max_retries', 3)
        new_count = current_retry + 1

        if new_count >= max_r:
            result = supabase.table('message_queue').update({
                'stage': 'dead',
                'retry_count': new_count,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', item['id']).eq('retry_count', current_retry).execute()
            if result.data:
                dead += 1
        else:
            result = supabase.table('message_queue').update({
                'stage': 'pending_ai_gen',
                'retry_count': new_count,
                'error_log': None,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', item['id']).eq('retry_count', current_retry).execute()
            if result.data:
                retried += 1

    return {'retried': retried, 'dead': dead}


def get_status(business_id=None):
    supabase = get_supabase()
    query = supabase.table('message_queue').select('stage', count='exact')

    if business_id:
        query = query.eq('business_id', business_id)

    all_items = query.execute()
    counts = {s: 0 for s in STAGES}
    for item in (all_items.data or []):
        stage = item.get('stage', '')
        counts[stage] = counts.get(stage, 0) + 1

    failed_query = supabase.table('message_queue').select(
        'id, customer_id, business_id, message_type, error_log, retry_count, created_at, updated_at'
    ).eq('stage', 'failed').order('updated_at', desc=True).limit(20)

    if business_id:
        failed_query = failed_query.eq('business_id', business_id)

    failed_items = failed_query.execute()

    items_query = supabase.table('message_queue').select(
        'id, customer_id, business_id, message_type, stage, sequence_day, error_log, retry_count, max_retries, scheduled_at, created_at, updated_at'
    ).order('created_at', desc=True).limit(200)

    if business_id:
        items_query = items_query.eq('business_id', business_id)

    items_data = items_query.execute()
    items = []

    if items_data.data:
        cust_ids = list(set(item.get('customer_id') for item in items_data.data if item.get('customer_id')))
        biz_ids = list(set(item.get('business_id') for item in items_data.data if item.get('business_id')))

        cust_map = {}
        if cust_ids:
            cust_result = supabase.table('customers').select('id, name, phone').in_('id', cust_ids).execute()
            cust_map = {c['id']: c for c in (cust_result.data or [])}

        biz_map = {}
        if biz_ids:
            biz_result = supabase.table('business_profiles').select('id, business_name').in_('id', biz_ids).execute()
            biz_map = {b['id']: b for b in (biz_result.data or [])}

        for item in items_data.data:
            c = cust_map.get(item.get('customer_id'), {})
            b = biz_map.get(item.get('business_id'), {})
            items.append({
                **item,
                'customer_name': c.get('name'),
                'customer_phone': c.get('phone'),
                'business_name': b.get('business_name'),
            })

    return {
        'counts': counts,
        'total': sum(counts.values()),
        'recent_failures': failed_items.data if failed_items.data else [],
        'items': items,
    }


def get_business_pipeline(business_id, limit=50):
    supabase = get_supabase()
    items = supabase.table('message_queue').select(
        'id, customer_id, message_type, stage, sequence_day, error_log, retry_count, scheduled_at, created_at, updated_at'
    ).eq('business_id', business_id).order('created_at', desc=True).limit(limit).execute()
    return items.data if items.data else []


def _update_customer_after_send(item):
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    customer_id = item.get('customer_id')
    business_id = item.get('business_id')
    text = item.get('ai_generated_text', '')

    supabase.table('messages').insert({
        'customer_id': customer_id,
        'business_id': business_id,
        'direction': 'sent',
        'content': text,
        'status': 'sent',
        'meta_message_id': item.get('meta_message_id'),
        'sequence_day': item.get('sequence_day'),
    }).execute()

    try:
        supabase.table('conversation_history').insert({
            'customer_id': customer_id,
            'role': 'model',
            'content': text,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to insert into conversation_history: {e}")

    if item.get('message_type') == 'sequence':
        seq_id = (item.get('payload') or {}).get('followup_sequence_id')
        if seq_id:
            from services.followup_service import complete_followup
            complete_followup(seq_id)

    supabase.table('customers').update({'last_contact': now}).eq(
        'id', customer_id
    ).execute()


def _handle_failure(item, error_msg):
    logger.error(f"Pipeline failure: queue_id={item.get('id')}, error={error_msg}")
    advance(item.get('id'), 'failed', {'error_log': error_msg}, expected_stage=None)

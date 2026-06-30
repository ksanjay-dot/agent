from database.supabase_client import get_supabase
from services.whatsapp_service import send_text_message
from datetime import datetime, timezone, timedelta
import logging
import time

logger = logging.getLogger(__name__)

CAMPAIGN_BATCH_SIZE = 500
MESSAGE_DELAY = 0.1
MAX_MESSAGE_LENGTH = 4096


def execute_campaign(campaign, business):
    supabase = get_supabase()
    biz_id = campaign.get('business_id')
    pn_id = business.get('meta_phone_number_id')
    if not pn_id:
        logger.error(f"No WhatsApp number for campaign {campaign.get('id')}")
        return

    message = (campaign.get('message') or '')[:MAX_MESSAGE_LENGTH]
    at = campaign.get('audience_type', 'all')
    af = campaign.get('audience_filter')

    total_sent = 0
    total_failed = 0
    offset = 0

    while True:
        query = supabase.table('customers').select('*').eq('business_id', biz_id)

        if at == 'inactive':
            thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            query = query.lt('last_contact', thirty_days_ago)
        elif at == 'product' and af and af.get('product'):
            query = query.eq('product', af['product'])
        elif at == 'custom' and af:
            if af.get('city'):
                query = query.eq('city', af['city'])
            if af.get('status'):
                query = query.eq('status', af['status'])
            if af.get('gender'):
                query = query.eq('gender', af['gender'])

        batch = query.range(offset, offset + CAMPAIGN_BATCH_SIZE - 1).execute()
        customers = batch.data or []
        if not customers:
            break

        for customer in customers:
            phone = customer.get('phone')
            if not phone:
                continue
            try:
                result = send_text_message(phone, message, phone_number_id=pn_id)
                if result.get('status') == 'success':
                    supabase.table('messages').insert({
                        'customer_id': customer['id'],
                        'business_id': biz_id,
                        'direction': 'sent',
                        'content': message,
                        'status': 'sent',
                        'meta_message_id': result.get('message_id'),
                        'campaign_id': campaign['id'],
                    }).execute()
                    total_sent += 1
                else:
                    total_failed += 1
            except Exception as e:
                total_failed += 1
                logger.warning(f"Campaign send failed (customer {customer.get('id')}): {str(e)[:100]}")

            time.sleep(MESSAGE_DELAY)

        offset += CAMPAIGN_BATCH_SIZE

    new_status = 'sent' if total_sent > 0 else 'failed'
    result = supabase.table('campaigns').update({
        'status': new_status,
        'messages_sent': total_sent,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }).eq('id', campaign.get('id')).execute()

    if not result.data:
        logger.error(f"Failed to update campaign {campaign.get('id')} status to {new_status}")

    logger.info(f"Campaign {campaign.get('id')}: sent {total_sent}, failed {total_failed}")

from celery_app import celery_app
from database.supabase_client import get_supabase
from services.campaign_service import execute_campaign
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@celery_app.task
def process_scheduled_campaigns():
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    due = supabase.table('campaigns').select('*').in_(
        'status', ['draft', 'scheduled']
    ).eq(
        'schedule_type', 'later'
    ).lte(
        'scheduled_at', now
    ).execute()

    sent = 0
    biz_ids = list(set(c.get('business_id') for c in due.data if c.get('business_id')))
    biz_map = {}
    if biz_ids:
        biz_result = supabase.table('business_profiles').select('id,business_name,*').in_('id', biz_ids).execute()
        biz_map = {b['id']: b for b in (biz_result.data or [])}

    for campaign in due.data:
        try:
            biz = biz_map.get(campaign.get('business_id'))
            if not biz:
                continue
            supabase.table('campaigns').update({
                'status': 'sending',
                'updated_at': now,
            }).eq('id', campaign['id']).execute()
            execute_campaign(campaign, biz)
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send scheduled campaign {campaign['id']}: {e}")
            supabase.table('campaigns').update({
                'status': 'failed',
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', campaign['id']).execute()

    if sent:
        logger.info(f"Sent {sent} scheduled campaign(s)")
    return {'sent': sent}

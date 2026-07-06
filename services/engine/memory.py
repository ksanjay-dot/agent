import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TZ_OFFSET = '+05:30'


def _parse_notes_section(notes: str, section_title: str) -> str:
    """Extract a section from the notes field like '=== Symptoms & Complaints ==='."""
    if not notes:
        return ''
    pattern = rf'===\s*{re.escape(section_title)}\s*===\s*(.*?)(?:\n\s*===|\Z)'
    m = re.search(pattern, notes, re.DOTALL)
    if m:
        text = m.group(1).strip()
        text = re.sub(r'\n- ', '\n', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if text in ('(skip)', '(No data)'):
            return ''
        return text[:300]
    return ''


def _calculate_days_since(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    try:
        if isinstance(date_str, str):
            d = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            d = date_str
        now = datetime.now(timezone.utc)
        delta = now - d
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None


def _summarize_history(history_data: list, max_exchanges: int = 3) -> str:
    """Build a one-line summary of the last few exchanges."""
    if not history_data:
        return ''
    recent = history_data[-max_exchanges:]
    summary = []
    for h in recent:
        role = 'Customer' if h.get('role') == 'user' else 'You'
        content = (h.get('content') or '')[:80]
        summary.append(f"{role}: {content}")
    return ' | '.join(summary)


def build_memory_profile(customer: dict, business: dict = None, supabase=None) -> dict:
    """Build a comprehensive MemoryProfile for a customer from existing data."""
    now = datetime.now(timezone.utc)

    notes = customer.get('notes') or ''
    complaints = _parse_notes_section(notes, 'Symptoms & Complaints')
    feedback = _parse_notes_section(notes, 'Key Feedback')

    days_since_purchase = _calculate_days_since(customer.get('purchase_date'))
    days_since_last_contact = _calculate_days_since(customer.get('last_contact'))
    days_since_returned = _calculate_days_since(customer.get('returned_at'))

    personality_raw = customer.get('personality_profile') or ''
    personality_tags = [t.strip() for t in personality_raw.split(',') if t.strip()]

    last_conversation_summary = ''
    if supabase and customer.get('id'):
        try:
            history = supabase.table('conversation_history').select('role,content') \
                .eq('customer_id', customer['id']) \
                .order('timestamp', desc=True) \
                .limit(5).execute()
            if history.data:
                history_reversed = list(reversed(history.data))
                last_conversation_summary = _summarize_history(history_reversed, 3)
        except Exception as e:
            logger.warning(f"Failed to fetch history for customer {customer.get('id')}: {e}")

    biz_type = (business.get('business_type') or '').lower() if business else ''
    industry = 'unknown'
    if 'dental' in biz_type or 'clinic' in biz_type:
        industry = 'dental'
    elif 'salon' in biz_type or 'spa' in biz_type:
        industry = 'salon'
    elif 'gym' in biz_type or 'fitness' in biz_type:
        industry = 'fitness'
    elif 'restaurant' in biz_type or 'food' in biz_type:
        industry = 'restaurant'
    elif 'hotel' in biz_type:
        industry = 'hotel'
    elif 'law' in biz_type or 'legal' in biz_type:
        industry = 'legal'

    return {
        'customer_name': customer.get('name', 'Customer'),
        'gender': customer.get('gender'),
        'product': customer.get('product') or customer.get('product_purchased') or '',
        'purchase_date': str(customer.get('purchase_date', '')),
        'days_since_purchase': days_since_purchase,
        'days_since_last_contact': days_since_last_contact,
        'days_since_returned': days_since_returned,
        'visit_count': customer.get('visit_count') or 0,
        'response_count': customer.get('response_count') or 0,
        'last_complaint': complaints,
        'last_feedback': feedback,
        'next_booking': customer.get('next_booking'),
        'status': customer.get('status', 'active'),
        'personality_tags': personality_tags,
        'last_conversation_summary': last_conversation_summary,
        'industry': industry,
        'business_name': business.get('business_name') if business else '',
        'best_contact_time': customer.get('best_contact_time'),
    }


def format_memory_block(memory: dict) -> str:
    """Format memory profile into a readable block for prompt injection."""
    lines = []
    lines.append(f"=== CUSTOMER MEMORY ===")
    lines.append(f"Name: {memory['customer_name']}")
    if memory.get('gender'):
        lines.append(f"Gender: {memory['gender']}")
    lines.append(f"Visit Count: {memory['visit_count']}")
    if memory['days_since_purchase'] is not None:
        lines.append(f"Days Since Purchase: {memory['days_since_purchase']}")
    if memory['days_since_last_contact'] is not None:
        lines.append(f"Days Since Last Contact: {memory['days_since_last_contact']}")
    lines.append(f"Product/Service: {memory['product']}")
    if memory.get('purchase_date'):
        lines.append(f"Purchase Date: {memory['purchase_date']}")
    if memory.get('last_complaint'):
        lines.append(f"Last Complaint: {memory['last_complaint']}")
    if memory.get('last_feedback'):
        lines.append(f"Last Feedback: {memory['last_feedback']}")
    if memory.get('next_booking'):
        lines.append(f"Next Appointment: {memory['next_booking']}")
    if memory.get('last_conversation_summary'):
        lines.append(f"Last Conversation: {memory['last_conversation_summary']}")
    if memory.get('personality_tags'):
        lines.append(f"Communication Style: {', '.join(memory['personality_tags'])}")
    if memory.get('industry'):
        lines.append(f"Industry: {memory['industry']}")
    lines.append("")
    return '\n'.join(lines)

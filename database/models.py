from dataclasses import dataclass
from typing import Optional
from datetime import date, datetime


@dataclass
class CustomerData:
    id: Optional[int] = None
    user_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    product: Optional[str] = None
    product_purchased: Optional[str] = None
    purchase_date: Optional[date] = None
    order_value: Optional[float] = None
    order_id: Optional[str] = None
    notes: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    current_sequence_day: Optional[int] = 0
    last_contact: Optional[datetime] = None
    response_count: Optional[int] = 0
    personality_profile: Optional[str] = 'unknown'
    best_contact_time: Optional[str] = None
    business_id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class BusinessProfileData:
    id: Optional[int] = None
    user_id: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    active_agent_id: Optional[int] = None


@dataclass
class AgentData:
    id: Optional[int] = None
    agent_name: Optional[str] = None
    personality_description: Optional[str] = None
    system_prompt: Optional[str] = None
    tone_tags: Optional[str] = None
    is_active: Optional[bool] = True


@dataclass
class MessageData:
    id: Optional[int] = None
    customer_id: Optional[int] = None
    business_id: Optional[int] = None
    direction: Optional[str] = None
    content: Optional[str] = None
    sequence_day: Optional[int] = None
    status: Optional[str] = 'sent'
    meta_message_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class ConversationHistoryData:
    id: Optional[int] = None
    customer_id: Optional[int] = None
    role: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class MessageQueueData:
    id: Optional[int] = None
    customer_id: Optional[int] = None
    business_id: Optional[int] = None
    message_type: Optional[str] = None
    stage: Optional[str] = 'pending_schedule'
    sequence_day: Optional[int] = None
    payload: Optional[dict] = None
    ai_generated_text: Optional[str] = None
    meta_message_id: Optional[str] = None
    error_log: Optional[str] = None
    retry_count: Optional[int] = 0
    max_retries: Optional[int] = 3
    scheduled_at: Optional[str] = None
    sent_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

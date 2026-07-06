from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv
import os
import emoji as emoji_lib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import asyncio

from services.engine import (
    build_memory_profile,
    format_memory_block,
    detect_formality,
    detect_customer_type,
    detect_personality as engine_detect_personality,
    detect_stop_signal,
    get_business_personality_rules,
    classify_emotion,
)

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(env_path)

logger = logging.getLogger(__name__)

TIMEZONE_OFFSET = os.getenv('TIMEZONE_OFFSET', '+05:30')

_api_key = os.getenv('OPENROUTER_API_KEY')
_base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
_default_headers = {
    'HTTP-Referer': 'https://cloud.vispace.in',
    'X-Title': 'VI Cloud',
}

client = OpenAI(
    api_key=_api_key,
    base_url=_base_url,
    default_headers=_default_headers,
)
async_client = AsyncOpenAI(
    api_key=_api_key,
    base_url=_base_url,
    default_headers=_default_headers,
)
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek/deepseek-v4-flash')
DEFAULT_MAX_TOKENS = int(os.getenv('DEEPSEEK_MAX_TOKENS', '150'))
DEFAULT_TEMPERATURE = float(os.getenv('DEEPSEEK_TEMPERATURE', '0.8'))

TIMELINE_INSTRUCTIONS = {
    'day_0': 'Welcome — First message after treatment. Warm, celebratory. Ask how they\'re feeling about their treatment today.',
    'day_0_3': 'Recovery check-in — Ask how they\'re feeling after the recent treatment. Reference their specific treatment. Show genuine concern.',
    'day_4_20': 'Wellness check — Ask if everything is still going well since their visit. Gentle check-in, no pressure.',
    'day_21_50': 'Deep engagement — Ask about overall satisfaction. Any feedback on their experience? Anything they\'d like to share?',
    'day_51_90': 'Re-engagement — Let them know you\'re thinking of them. Ask how they\'ve been. Subtle invite to visit if they feel the need.',
    'day_90_plus': 'Long-term check — It\'s been a while since you last visited. Hope everything is going well. Door is always open.',
}

BOOK_APPOINTMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "book_appointment",
        "description": "Book a follow-up appointment for the customer when they agree to visit",
        "parameters": {
            "type": "object",
            "properties": {
                "date_time": {
                    "type": "string",
                    "description": "Appointment date and time in ISO 8601 format with IST timezone offset, e.g. 2026-06-15T10:00:00+05:30. CRITICAL: You MUST append +05:30 to the time so the database stores it correctly. Use the EXACT time the customer mentioned. If customer says 'tomorrow at 5pm', use the correct date with 17:00:00+05:30. Only use 10:00:00+05:30 if the customer did NOT specify any time.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for the appointment, e.g. 'tooth pain check-up'",
                },
            },
            "required": ["date_time"],
        },
    },
}

OLD_SEQUENCE_INSTRUCTIONS = {
    0: "Welcome - First message after purchase. Warm, celebratory, genuine. Ask how they're feeling about their purchase.",
    1: "First check-in - Ask about their experience so far. How are they feeling? Any feedback?",
    2: "Second check-in - Follow up on their progress. Ask if they have any questions or concerns.",
    3: "Third check-in - Deeper engagement. Ask about results, satisfaction, and overall experience.",
    4: "Fourth check-in - Relationship strengthening. Ask for feedback, suggestions, how they're really doing.",
    5: "Fifth check-in - Check if everything is still going well. Offer help if needed.",
}

SEQUENCE_INSTRUCTIONS = OLD_SEQUENCE_INSTRUCTIONS


def _get_timeline_instruction(days_since_purchase: int = None) -> str:
    if days_since_purchase is None:
        return TIMELINE_INSTRUCTIONS['day_0_3']
    if days_since_purchase == 0:
        return TIMELINE_INSTRUCTIONS['day_0']
    elif days_since_purchase <= 3:
        return TIMELINE_INSTRUCTIONS['day_0_3']
    elif days_since_purchase <= 20:
        return TIMELINE_INSTRUCTIONS['day_4_20']
    elif days_since_purchase <= 50:
        return TIMELINE_INSTRUCTIONS['day_21_50']
    elif days_since_purchase <= 90:
        return TIMELINE_INSTRUCTIONS['day_51_90']
    else:
        return TIMELINE_INSTRUCTIONS['day_90_plus']


def _safe_text(response):
    if response and response.choices:
        content = response.choices[0].message.content
        return content.strip() if content else ''
    return ''


def build_system_prompt(agent, business, customer, memory_profile=None, supabase=None, conversation_goal=None, emotion=None, customer_message=None):
    system_prompt = (agent.get('system_prompt') or '').replace(
        '{business_name}', business.get('business_name', '')
    ).replace(
        '{business_type}', business.get('business_type', '')
    )

    if memory_profile is None:
        memory_profile = build_memory_profile(customer, business, supabase)

    memory_block = format_memory_block(memory_profile)
    system_prompt += f"\n\n{memory_block}\n"

    biz_personality = business.get('brand_personality', 'friendly_dentist')
    personality_rules = get_business_personality_rules(biz_personality)
    system_prompt += f"\n{personality_rules}\n"

    if conversation_goal:
        lines = ["\n=== CONVERSATION GOALS ==="]
        for key, val in conversation_goal.items():
            if val:
                lines.append(f"{key.replace('_', ' ').title()}: {val}")
        system_prompt += '\n'.join(lines) + '\n'

    if emotion:
        system_prompt += f"\nCustomer Emotion Detected: {emotion}\n"
        if emotion in ('angry', 'disappointed'):
            system_prompt += "- Show empathy first. Apologize sincerely. Don't be defensive.\n- Understand their concern before offering solutions.\n- Never use scripted or templated responses.\n"
        elif emotion == 'confused':
            system_prompt += "- Be clear and patient. Explain simply.\n- Ask clarifying questions gently.\n- Offer to help them understand.\n"
        elif emotion == 'excited':
            system_prompt += "- Match their enthusiasm! Celebrate with them.\n- Be genuinely happy in your response.\n"
        elif emotion == 'happy':
            system_prompt += "- 'Aww that's lovely!' style. Warm and genuine.\n- Small celebration is appropriate.\n"

    biz_type = (business.get('business_type') or '').lower()

    if customer_message:
        formality = detect_formality(customer_message)
        if formality == 'formal':
            system_prompt += "\nCUSTOMER FORMALITY: Formal. Use respectful language. Address them appropriately. No casual slang or emojis unless they use them first.\n"
        elif formality == 'casual':
            system_prompt += "\nCUSTOMER FORMALITY: Casual. Use casual language freely. Emojis are great. Be warm and friendly like texting a friend.\n"
        else:
            system_prompt += "\nCUSTOMER FORMALITY: Neutral. Match their tone naturally.\n"

    customer_type = detect_customer_type(customer)
    if customer_type == 'vip':
        system_prompt += "\nThis is a VIP customer (5+ visits). Show appreciation for their loyalty. 'We really appreciate your trust in us.'\n"
    elif customer_type == 'first_time':
        system_prompt += "\nThis is a first-time customer. Make them feel welcome and special. Extra warmth.\n"
    elif customer_type == 'silent':
        system_prompt += "\nThis customer hasn't responded recently. Keep the message low-pressure and gentle. No questions that demand an answer.\n"
    elif customer_type == 'complainer':
        system_prompt += "\nThis customer has had complaints before. Be extra empathetic. Acknowledge past issues if relevant. Show you remember.\n"
    elif customer_type == 'loyal':
        system_prompt += "\nThis is a loyal customer (3+ visits). Warm and familiar. They know us well.\n"

    stop_signal = False
    if customer_message:
        stop_signal = detect_stop_signal(customer_message)
    if stop_signal:
        system_prompt += "\nIMPORTANT: The customer is signaling the end of conversation. If they're thanking you, send ONE brief warm reply and that's it. Do NOT ask follow-up questions or continue the conversation.\n"
    else:
        system_prompt += """
PURPOSEFUL MESSAGING:
- Every message must have a genuine reason. Never message just to say "Hi, how are you?"
- Reference their specific situation (treatment, purchase, last conversation).
- Show you remember them as an individual.

SHOW CONCERN FIRST:
- Before any ask or suggestion, show genuine care.
- "Hope everything's been going well since your visit. How are you feeling?"
- Never lead with a request or promotion.

NO ROBOTIC QUESTIONS:
- Instead of "Please provide your feedback", say "We'd genuinely love to know — was there anything we could have done to make your experience even better?"
- Instead of "Would you like to book?", say "If you ever feel the need, we're here for you."
"""

    if customer.get('next_booking'):
        nb = customer['next_booking']
        system_prompt += f"""
IMPORTANT: This customer already has a follow-up appointment booked for {nb}.
- If the issue can wait, remind them of their existing appointment.
- If urgent, suggest they come in sooner.
"""

    if 'dental' in biz_type or 'clinic' in biz_type or 'health' in biz_type:
        tz_offset = TIMEZONE_OFFSET
        tz_hours = int(tz_offset.split(':')[0]) if '+' in tz_offset else -int(tz_offset.split(':')[0].replace('-', ''))
        tz_mins = int(tz_offset.split(':')[1]) if ':' in tz_offset else 0
        tz_delta = timedelta(hours=tz_hours, minutes=tz_mins)
        ist_now = datetime.now(timezone.utc) + tz_delta
        today = ist_now.date().isoformat()
        tomorrow_d = (ist_now.date() + timedelta(days=1)).isoformat()
        system_prompt += f"""
WARMTH RULES — Sound like a real human caring for a friend:
- Always start with a warm reaction to what the customer said. "Oh that's so good to hear! 🎉", "Oh no that sounds painful 😟", "Haha nice!", "Aww that's sweet!"
- Use emojis freely — at least 1 emoji per message. They show emotion.
- Sound like you're texting a friend, not a customer service agent.
- Use casual words: "hey", "awesome", "got it", "no worries", "take your time"
- Never use corporate or clinical language.
- Show genuine happiness/concern before saying anything else.

LENGTH RULES (CRITICAL):
- MAXIMUM 2-3 SENTENCES per message.
- MAXIMUM 40 WORDS. Shorter is better.
- If you have multiple things to say, pick the most important ONE.
- Never write paragraphs. Never.

CONVERSATION FLOW:
- First, react to what they said with genuine emotion.
- Then ask ONE gentle question or say something caring.
- That's it. Don't stack multiple questions. Don't over-explain.

QUESTIONING:
- You don't need to ask a question every time. Sometimes just a warm check-in is enough.
- If you do ask, ask ONE thing. Not multiple questions.
- Focus on how they're FEELING, not on getting information.

APPOINTMENTS:
- NEVER suggest booking an appointment unless the customer directly asks or the issue sounds genuinely serious (unbearable pain, infection symptoms).
- If they mention mild discomfort, just acknowledge it with empathy — don't jump to booking.
- If they already have a booking scheduled, just acknowledge it gently once, don't keep reminding.
- The relationship comes first. Appointments come naturally when trust is built.

BOOKING FUNCTION:
Only available if customer asks to book. When they do, use "{tomorrow_d}T10:00:00+05:30" as default if no time specified.
"""
    else:
        system_prompt += """
WARMTH RULES — Sound like a real person:
- React with genuine emotion. "That's awesome! 😄", "Oh nice!", "Haha love it!"
- Use emojis freely — at least 1 per message.
- Keep messages SHORT — 15-20 words, like a WhatsApp text.

LENGTH RULES (CRITICAL):
- MAXIMUM 2 SENTENCES per message.
- MAXIMUM 40 WORDS. Shorter is better.
- Pick ONE thing to say or ask. Not multiple.

GENERAL CONVERSATION:
- Focus on how they're feeling about the product.
- Ask one gentle question if it feels natural. But you don't have to.
- No sales, no pushing, just genuine check-in.
"""

    agent_name = (agent.get('agent_name') or '').lower()
    system_prompt += """
REACTION HANDLING:
- If the customer sends "reacted with ❤️", they heart-reacted to your last message.
"""
    if agent_name == 'nisha':
        system_prompt += """- Be flirtatious, sassy, and playful. Make them smile.
  "Ayyy thank you! ❤️", "I know right? 😉", "You're making me blush! 🥰"
- Use wink emojis 😉 and heart eyes 🥰
- Keep it fun and cheeky — make them want to react again"""
    elif agent_name == 'arjun':
        system_prompt += """- Acknowledge professionally with polite gratitude.
  "Thank you, much appreciated."
- Keep it warm but professional. No flirting."""
    else:
        system_prompt += """- Respond warmly with genuine gratitude.
  "Aww thank you! ❤️ That made my day! 😊"
- Match their energy — be extra warm and loving."""

    return system_prompt


RETRYABLE_STATUSES = ('503', '429', '500', '502', '504')


def _is_retryable(e: Exception) -> bool:
    err_str = str(e)
    status_match = any(f'"{s}"' in err_str or f' {s} ' in err_str or err_str.startswith(s) or f'HTTP {s}' in err_str for s in RETRYABLE_STATUSES)
    return status_match or 'quota' in err_str.lower() or 'rate limit' in err_str.lower() or 'timeout' in err_str.lower()


def _deepseek_retry(fn, max_retries=3, base_delay=2):
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if _is_retryable(e):
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"DeepSeek error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {str(e)[:100]}")
                    time.sleep(delay)
            else:
                raise
    raise last_error


async def _adeepseek_retry(fn, max_retries=3, base_delay=2):
    last_error = None
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as e:
            if _is_retryable(e):
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"DeepSeek error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {str(e)[:100]}")
                    await asyncio.sleep(delay)
            else:
                raise
    raise last_error


def generate_followup_message(customer, business, agent, sequence_day):
    supabase = None
    try:
        from database.supabase_client import get_supabase
        supabase = get_supabase()
    except Exception:
        pass

    memory_profile = build_memory_profile(customer, business, supabase)
    days_since = memory_profile.get('days_since_purchase')
    timeline_instruction = _get_timeline_instruction(days_since)

    system_prompt = build_system_prompt(
        agent, business, customer,
        memory_profile=memory_profile,
        supabase=supabase,
        conversation_goal={'primary_goal': timeline_instruction},
    )

    prompt = f"""
    Customer Name: {memory_profile['customer_name']}
    Product/Service: {memory_profile['product']}
    Days Since Purchase: {days_since if days_since is not None else 'unknown'}
    Visit Count: {memory_profile['visit_count']}
    Business Name: {memory_profile['business_name']}

    Context: {timeline_instruction}

    Generate the WhatsApp message now.
    Only output the message text. Nothing else.
    No quotes, no labels, no explanation.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    response = _deepseek_retry(lambda: client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        max_tokens=150,
        temperature=0.8,
    ))
    return _safe_text(response)


async def generate_reply(customer, business, agent, customer_message, history, supabase=None):
    emotion = classify_emotion(customer_message)

    memory_profile = build_memory_profile(customer, business, supabase)

    conversation_goal = {
        'primary_goal': 'Respond to the customer\'s message naturally and helpfully.',
        'secondary_goal': 'Address their concern or question directly.',
    }

    if supabase:
        try:
            current_state = customer.get('conversation_state') or {}
            if isinstance(current_state, str):
                current_state = json.loads(current_state) if current_state else {}
            if emotion in ('angry', 'disappointed'):
                current_state['state'] = 'unsatisfied'
                current_state['sub_state'] = emotion
            elif emotion == 'happy':
                current_state['state'] = 'satisfied'
            supabase.table('customers').update({
                'conversation_state': json.dumps(current_state) if isinstance(current_state, dict) else current_state,
            }).eq('id', customer['id']).execute()
        except Exception as e:
            logger.warning(f"Failed to update conversation_state: {e}")

    system_prompt = build_system_prompt(
        agent, business, customer,
        memory_profile=memory_profile,
        supabase=supabase,
        conversation_goal=conversation_goal,
        emotion=emotion,
        customer_message=customer_message,
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append({
            "role": "user" if msg.get('role') == 'user' else "assistant",
            "content": msg.get('content', ''),
        })
    messages.append({"role": "user", "content": customer_message})

    first_call = await _adeepseek_retry(lambda: async_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
        tools=[BOOK_APPOINTMENT_TOOL],
    ))

    if not first_call.choices:
        logger.error("LLM returned no choices")
        return ""

    choice = first_call.choices[0]
    msg = choice.message

    if msg.tool_calls:
        tc = msg.tool_calls[0]
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tool call arguments: {e}")
            args = {}
        date_time = args.get('date_time', '')
        reason = args.get('reason', '')

        if date_time and '+' not in date_time and 'Z' not in date_time:
            date_time = date_time + TIMEZONE_OFFSET

        if supabase and customer.get('id'):
            result = supabase.table('customers').update({
                'next_booking': date_time,
            }).eq('id', customer['id']).execute()
            if not result.data:
                logger.warning(f"Failed to update next_booking for customer {customer['id']}")

        customer['next_booking'] = date_time

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": f"Appointment booked for {date_time}" + (f" ({reason})" if reason else ""),
        })

        second = await _adeepseek_retry(lambda: async_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=DEFAULT_TEMPERATURE,
        ))
        return _safe_text(second)

    return _safe_text(first_call)


def generate_appointment_message(customer, business, agent, message_type):
    supabase = None
    try:
        from database.supabase_client import get_supabase
        supabase = get_supabase()
    except Exception:
        pass

    memory_profile = build_memory_profile(customer, business, supabase)

    system_prompt = build_system_prompt(
        agent, business, customer,
        memory_profile=memory_profile,
        supabase=supabase,
    )
    today = datetime.now(timezone.utc).date().isoformat()

    if message_type == 'reminder':
        prompt = f"""
Customer Name: {memory_profile['customer_name']}
Appointment: {customer.get('next_booking', 'No appointment set')}
Business: {memory_profile['business_name']}

Today's date: {today}

You are reminding the customer about their upcoming appointment.
Be warm and helpful. Confirm the appointment time and ask if they need to reschedule.
Only output the message text. Nothing else. No quotes.
"""
    elif message_type == 'followup':
        prompt = f"""
Customer Name: {memory_profile['customer_name']}
Business: {memory_profile['business_name']}
Last appointment: {customer.get('next_booking', 'No appointment set')}
Product purchased: {memory_profile['product']}

Today's date: {today}

This customer had an appointment yesterday. Follow up with them — ask how it went,
if they're feeling better, and if they need anything more. Be caring, not salesy.
Only output the message text. Nothing else. No quotes.
"""
    else:
        raise ValueError(f"Unknown message_type: {message_type}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    response = _deepseek_retry(lambda: client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        max_tokens=150,
        temperature=0.8,
    ))

    return _safe_text(response)


def detect_personality(message_text):
    result = engine_detect_personality(message_text)
    tags = result.get('tags', ['neutral'])
    return ','.join(tags) if tags else 'neutral'


def extract_notes_from_conversation(customer, business, conversation_history, existing_notes=None):
    if not conversation_history:
        return None

    history_text = "\n".join(
        f"{'Customer' if m['role'] == 'user' else 'Agent'}: {m['content']}"
        for m in conversation_history
    )
    product = customer.get('product_purchased') or customer.get('product', '')

    existing_block = ""
    if existing_notes:
        existing_block = f"""
Previous notes (merge new info into these, don't discard what's still relevant):
{existing_notes}
"""

    prompt = f"""You are a clinical note-taking assistant for {business.get('business_name', 'the business')}, a {business.get('business_type', 'business')}.

Customer: {customer.get('name', 'Unknown')}
Product/Service: {product}
{existing_block}
Read the FULL conversation below and produce a clean, doctor-friendly clinical note in this format:

=== Symptoms & Complaints ===
Bullet points only. What hurts, where, how bad (scale 1-10), type of pain (sharp/dull/throbbing), duration, triggers. If nothing shared: skip section.

=== Current Status ===
One line summarizing how the patient is feeling NOW. Exact words if relevant.
If nothing shared: skip section.

=== Key Feedback ===
Brief notes on what the customer said about the treatment/product. Include direct quotes in "quotes".
If nothing shared: skip section.

=== Appointments ===
Any booked follow-ups, reschedules, or preferences.
If nothing shared: skip section.

Full Conversation:
{history_text}

IMPORTANT:
- ONLY include sections that have actual data. Skip empty sections entirely.
- Be BRIEF. A doctor should read this in 10 seconds.
- Use bullet points (-), not numbers.
- No markdown formatting other than simple bullet points.
- No greetings, no explanations, no labels like "Here is the summary".
- Just output the sections with data. Nothing else.
- If previous notes were provided, UPDATE them with new info from the latest conversation. Keep what's still accurate, add what's new."""

    messages = [
        {"role": "system", "content": prompt},
    ]

    try:
        response = _deepseek_retry(lambda: client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            max_tokens=600,
            temperature=0.3,
        ))
        return _safe_text(response)
    except Exception as e:
        logger.error(f"Notes extraction failed: {e}")
        return None

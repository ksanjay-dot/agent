from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv
import os
import emoji
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import asyncio

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

SEQUENCE_INSTRUCTIONS = {
    0: "Welcome - First message after purchase. Warm, celebratory, genuine. Ask how they're feeling about their purchase.",
    1: "First check-in - Ask about their experience so far. How are they feeling? Any feedback?",
    2: "Second check-in - Follow up on their progress. Ask if they have any questions or concerns.",
    3: "Third check-in - Deeper engagement. Ask about results, satisfaction, and overall experience.",
    4: "Fourth check-in - Relationship strengthening. Ask for feedback, suggestions, how they're really doing.",
    5: "Fifth check-in - Check if everything is still going well. Offer help if needed.",
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


def _safe_text(response):
    if response and response.choices:
        content = response.choices[0].message.content
        return content.strip() if content else ''
    return ''


def build_system_prompt(agent, business, customer):
    system_prompt = (agent.get('system_prompt') or '').replace(
        '{business_name}', business.get('business_name', '')
    ).replace(
        '{business_type}', business.get('business_type', '')
    )

    biz_type = (business.get('business_type') or '').lower()

    system_prompt += f"""
\nCustomer personality detected: {customer.get('personality_profile', 'unknown')}
Match their communication style exactly.
Customer name: {customer.get('name', 'Customer')}
Product they purchased: {customer.get('product_purchased') or customer.get('product', '')}
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

    if customer.get('next_booking'):
        nb = customer['next_booking']
        system_prompt += f"""
IMPORTANT: This customer already has a follow-up appointment booked for {nb}.
- If the issue can wait, remind them of their existing appointment.
- If urgent, suggest they come in sooner.
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
    system_prompt = build_system_prompt(agent, business, customer)
    prompt = f"""
    Customer Name: {customer.get('name', 'Customer')}
    Product Purchased: {customer.get('product_purchased') or customer.get('product', '')}
    Purchase Date: {customer.get('purchase_date', '')}
    Business Name: {business.get('business_name', '')}
    Customer Personality: {customer.get('personality_profile', 'unknown')}
    Sequence: {SEQUENCE_INSTRUCTIONS.get(sequence_day, '')}

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
    system_prompt = build_system_prompt(agent, business, customer)

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
    system_prompt = build_system_prompt(agent, business, customer)
    today = datetime.now(timezone.utc).date().isoformat()

    if message_type == 'reminder':
        prompt = f"""
Customer Name: {customer.get('name', 'Customer')}
Appointment: {customer.get('next_booking', 'No appointment set')}
Business: {business.get('business_name', '')}

Today's date: {today}

You are reminding the customer about their upcoming appointment.
Be warm and helpful. Confirm the appointment time and ask if they need to reschedule.
Only output the message text. Nothing else. No quotes.
"""
    elif message_type == 'followup':
        prompt = f"""
Customer Name: {customer.get('name', 'Customer')}
Business: {business.get('business_name', '')}
Last appointment: {customer.get('next_booking', 'No appointment set')}
Product purchased: {customer.get('product_purchased') or customer.get('product', '')}

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
    text = message_text.lower()
    tags = []

    if len(message_text) < 20:
        tags.append('brief')
    elif len(message_text) > 100:
        tags.append('detailed')

    if emoji.emoji_count(message_text) > 0:
        tags.append('casual')

    formal_words = ['dear', 'respected', 'regards', 'sincerely', 'kindly']
    if any(word in text for word in formal_words):
        tags.append('formal')

    hindi_words = ['hai', 'kya', 'acha', 'theek', 'haan', 'nahi',
                   'bhai', 'yaar', 'bol', 'kar', 'tha', 'thi']
    if sum(1 for word in hindi_words if word in text) >= 2:
        tags.append('hinglish')

    humor_indicators = ['lol', 'haha', 'hehe', 'lmao', '\U0001f602', '\U0001f923']
    if any(h in text for h in humor_indicators):
        tags.append('humorous')

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

import emoji
import logging

logger = logging.getLogger(__name__)

STOP_SIGNALS = [
    'thank you', 'thanks', 'thanku', 'thankyou', 'thx',
    'ok thanks', 'okay thanks', 'ok thank you',
    'take care', 'tc', 'bye', 'goodbye', 'see you',
    'that\'s all', 'that is all', 'thats all',
    'ok bye', 'okay bye',
    'no thanks', 'no thank you', 'no thx',
    'will visit soon', 'will come soon',
    'got it', 'ok got it', 'okay got it',
    'sure thanks', 'sure thank you',
    'thanks a lot', 'thank you so much',
]

FORMAL_INDICATORS = [
    'dear', 'respected', 'regards', 'sincerely', 'kindly',
    'sir', 'madam', 'ma\'am', 'mr.', 'mrs.', 'ms.',
]

CASUAL_INDICATORS = [
    'bro', 'dude', 'hey', 'yo', 'chill', 'awesome',
    'lol', 'lmao', 'lmfao', 'haha', 'hehe',
    'nah', 'yeah', 'yep', 'nope', 'gonna', 'wanna',
    'btw', 'omg', 'tbh', 'afk', 'brb',
]

HINGLISH_INDICATORS = [
    'hai', 'kya', 'acha', 'theek', 'haan', 'nahi',
    'bhai', 'yaar', 'bol', 'kar', 'tha', 'thi',
    'ho', 'hain', 'kaise', 'kyaa', 'accha', 'thik',
]


def detect_formality(text: str) -> str:
    """Detect communication formality level: casual, neutral, or formal."""
    if not text:
        return 'neutral'
    text_lower = text.lower()

    formal_score = sum(1 for w in FORMAL_INDICATORS if w in text_lower)
    casual_score = sum(1 for w in CASUAL_INDICATORS if w in text_lower)
    hinglish_score = sum(1 for w in HINGLISH_INDICATORS if w in text_lower)
    has_emoji = emoji.emoji_count(text) > 0

    if has_emoji:
        casual_score += 1

    if formal_score > casual_score:
        return 'formal'
    elif casual_score > 0 or hinglish_score >= 2 or has_emoji:
        return 'casual'
    else:
        return 'neutral'


def detect_customer_type(customer: dict) -> str:
    """Classify customer into a type based on their behavior data."""
    visit_count = customer.get('visit_count') or 0
    response_count = customer.get('response_count') or 0
    status = customer.get('status') or 'active'
    notes = customer.get('notes') or ''

    has_complaint = 'complaint' in notes.lower() or 'pain' in notes.lower() or 'issue' in notes.lower()
    is_vip = visit_count >= 5

    if is_vip:
        return 'vip'
    if visit_count == 0:
        return 'first_time'
    if status == 'paused':
        return 'silent'
    if response_count == 0 and visit_count > 0:
        return 'silent'
    if has_complaint and response_count > 0:
        return 'complainer'
    if visit_count == 1:
        return 'new'
    if visit_count >= 3:
        return 'loyal'
    return 'regular'


def detect_personality(message_text: str) -> dict:
    """Enhanced personality detection returning structured result."""
    result = {
        'tags': [],
        'formality': 'neutral',
        'length': 'medium',
    }
    if not message_text:
        return result

    text = message_text.lower()

    length = len(message_text)
    if length < 20:
        result['length'] = 'brief'
    elif length > 100:
        result['length'] = 'detailed'
    else:
        result['length'] = 'medium'

    if emoji.emoji_count(message_text) > 0:
        result['tags'].append('casual')

    result['formality'] = detect_formality(message_text)

    if result['formality'] == 'formal':
        result['tags'].append('formal')
    elif result['formality'] == 'casual':
        result['tags'].append('casual')
    else:
        result['tags'].append('neutral')

    hinglish_score = sum(1 for w in HINGLISH_INDICATORS if w in text)
    if hinglish_score >= 2:
        result['tags'].append('hinglish')

    humor_words = ['lol', 'haha', 'hehe', 'lmao', '😂', '🤣']
    if any(h in text for h in humor_words):
        result['tags'].append('humorous')

    result['tags'] = list(set(result['tags']))

    return result


def detect_stop_signal(message_text: str) -> bool:
    """Check if a message signals the conversation should end."""
    if not message_text:
        return False
    text = message_text.lower().strip()

    text_clean = text.replace('.', '').replace(',', '').replace('!', '').replace('?', '').strip()
    text_clean = text_clean.replace('\u2764', '').replace('\u2665', '').replace('\U0001f60a', '').strip()

    for signal in STOP_SIGNALS:
        if text_clean == signal or text_clean.startswith(signal + ' ') or text_clean.endswith(' ' + signal):
            return True

    if len(text_clean.split()) <= 3:
        short_enders = {'ok', 'okay', 'k', 'kk', 'fine', 'good', 'nice', 'sure'}
        if text_clean in short_enders:
            return True

    return False


BUSINESS_PERSONALITIES = {
    'friendly_dentist': {
        'tone': 'Warm, caring, clinically informed but not technical. Like a trustworthy dentist who genuinely remembers you.',
        'emoji_style': 'moderate — one per message to show warmth',
        'focus': 'Recovery, comfort, treatment outcomes, preventive care',
        'avoid': 'Scare tactics, hard selling, overly clinical jargon',
        'greeting_style': 'friendly but respectful — never overly casual',
        'sign_off_style': 'warm check-in, no pressure to book',
    },
    'luxury_salon': {
        'tone': 'Polished, elegant, pampering. Like a high-end stylist who knows your preferences.',
        'emoji_style': 'minimal — elegant emojis only ✨💫',
        'focus': 'Look, feel, style, self-care',
        'avoid': 'Clinical or medical language',
        'greeting_style': 'sophisticated and flattering',
        'sign_off_style': 'elegant reminder of their next visit',
    },
    'professional_lawyer': {
        'tone': 'Formal, precise, trustworthy. Like a reliable legal advisor.',
        'emoji_style': 'none unless customer uses them first',
        'focus': 'Case progress, documents, deadlines, follow-ups',
        'avoid': 'Casual slang, emojis, overly familiar language',
        'greeting_style': 'Mr./Ms. Last Name when possible',
        'sign_off_style': 'clear next steps',
    },
    'family_restaurant': {
        'tone': 'Warm, hearty, familiar. Like a favorite waiter who remembers your order.',
        'emoji_style': 'generous — emojis show the food love 🍕😋',
        'focus': 'Food experience, special occasions, new menu items',
        'avoid': 'Formality, clinical language',
        'greeting_style': 'cheerful and personal',
        'sign_off_style': 'looking forward to serving again',
    },
    'modern_startup': {
        'tone': 'Energetic, helpful, direct. Like a helpful product person who actually cares.',
        'emoji_style': 'moderate — modern and friendly',
        'focus': 'Product experience, feedback, onboarding, features',
        'avoid': 'Stuffy formality, overly salesy language',
        'greeting_style': 'casual and direct',
        'sign_off_style': 'open-ended help offer',
    },
    'friendly_gym': {
        'tone': 'Motivational, energetic, encouraging. Like a personal trainer who notices when you skip.',
        'emoji_style': 'generous — high energy 💪🔥',
        'focus': 'Progress, consistency, goals, class schedules',
        'avoid': 'Sedentary language, food-focused talk',
        'greeting_style': 'high energy and personal',
        'sign_off_style': 'motivational push',
    },
}


def get_business_personality_rules(personality_name: str) -> str:
    """Get formatted rules for a business personality type."""
    if not personality_name:
        personality_name = 'friendly_dentist'
    personality = BUSINESS_PERSONALITIES.get(personality_name)
    if not personality:
        personality = BUSINESS_PERSONALITIES['friendly_dentist']
    lines = [
        f"=== BUSINESS PERSONALITY: {personality_name.replace('_', ' ').title()} ===",
        f"Tone: {personality['tone']}",
        f"Emoji Style: {personality['emoji_style']}",
        f"Conversation Focus: {personality['focus']}",
        f"Greeting Style: {personality['greeting_style']}",
        f"Sign-off Style: {personality['sign_off_style']}",
        f"Avoid: {personality['avoid']}",
    ]
    return '\n'.join(lines)

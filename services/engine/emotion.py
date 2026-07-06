import logging
import re
import emoji as emoji_lib

logger = logging.getLogger(__name__)

EMOTIONS = ['happy', 'neutral', 'confused', 'angry', 'disappointed', 'excited']

HAPPY_KEYWORDS = [
    'happy', 'great', 'wonderful', 'awesome', 'amazing', 'fantastic',
    'love', 'loved', 'beautiful', 'perfect', 'excellent', ' superb',
    'pleased', 'delighted', 'satisfied', 'good', 'nice', 'best',
    'thank', 'thanks', 'grateful', 'enjoy', 'enjoyed', 'glad',
    'better', 'improved', 'healed', 'fine', 'okay', 'alright',
]

ANGRY_KEYWORDS = [
    'angry', 'furious', 'terrible', 'horrible', 'worst', 'awful',
    'useless', 'pathetic', 'scam', 'cheat', 'cheated', 'fraud',
    'complaint', 'unacceptable', 'ridiculous', 'annoying',
    'frustrating', 'frustrated', 'fed up', 'sick of', 'tired of',
    'waste', 'useless', 'disgusting', 'shameful',
]

DISAPPOINTED_KEYWORDS = [
    'disappointed', 'disappointing', 'sad', 'unfortunately', 'unhappy',
    'not good', 'not great', 'not happy', 'could be better',
    'expected more', 'let down', 'dissatisfied', 'unfortunately',
    'wish it was', 'not what i expected', 'below average',
    'not satisfied', 'not pleased', 'not well', 'still hurting',
    'still pain', 'not improved', 'didn\'t help', 'no change',
]

CONFUSED_KEYWORDS = [
    'confused', 'not sure', 'i don\'t understand', 'what does',
    'how does', 'explain', 'i don\'t get', 'unclear', 'what do you mean',
    'can you clarify', 'i\'m not following', 'huh', 'what?',
    'sorry?', 'pardon', 'come again', 'i don\'t know',
]

EXCITED_KEYWORDS = [
    'excited', 'amazing', 'can\'t wait', 'looking forward',
    'thrilled', 'pumped', 'hyped', 'lets go',
    'yay', 'woohoo', 'finally', 'so ready',
    'made my day', 'incredible', 'wow',
]

HAPPY_EMOJIS = {'😊', '😄', '😁', '😀', '🙂', '😍', '🥰', '😘', '❤️', '💕', '🎉', '🥳', '✨', '🌟', '💫'}
ANGRY_EMOJIS = {'😡', '😠', '🤬', '👿', '💢', '👊'}
DISAPPOINTED_EMOJIS = {'😞', '😔', '😢', '😥', '😓', '😩', '😫', '😭', '💔'}
CONFUSED_EMOJIS = {'🤔', '😕', '😐', '🤨', '🧐', '❓', '⁉️'}
EXCITED_EMOJIS = {'🤩', '😱', '🔥', '💯', '🎉', '🥳', '🚀', '💪', '⚡'}


def classify_emotion(message_text: str) -> str:
    """Classify the emotion of a customer message. Returns one of: happy, neutral, confused, angry, disappointed, excited."""
    if not message_text:
        return 'neutral'

    text_lower = message_text.lower().strip()
    if not text_lower:
        return 'neutral'

    scores = {e: 0 for e in EMOTIONS}

    emoji_chars = set()
    try:
        emoji_list = emoji_lib.emoji_list(message_text)
        emoji_chars = {e['emoji'] for e in emoji_list}
    except Exception:
        pass
    if not emoji_chars:
        emoji_chars = {c for c in message_text if c in HAPPY_EMOJIS or c in ANGRY_EMOJIS or c in DISAPPOINTED_EMOJIS or c in CONFUSED_EMOJIS or c in EXCITED_EMOJIS}

    for em in emoji_chars:
        if em in HAPPY_EMOJIS:
            scores['happy'] += 3
        if em in ANGRY_EMOJIS:
            scores['angry'] += 3
        if em in DISAPPOINTED_EMOJIS:
            scores['disappointed'] += 3
        if em in CONFUSED_EMOJIS:
            scores['confused'] += 3
        if em in EXCITED_EMOJIS:
            scores['excited'] += 3

    text_clean = re.sub(r'[^a-z0-9\s]', ' ', text_lower)
    clean_words = set(text_clean.split())

    for kw in HAPPY_KEYWORDS:
        kw_clean = kw.strip()
        if kw_clean in clean_words:
            scores['happy'] += 1

    for kw in ANGRY_KEYWORDS:
        kw_clean = kw.strip()
        kw_words = kw_clean.split()
        if len(kw_words) > 1:
            if kw_clean in text_clean:
                scores['angry'] += 2
                scores['disappointed'] += 1
        elif kw_clean in clean_words:
            scores['angry'] += 2
            scores['disappointed'] += 1

    for kw in DISAPPOINTED_KEYWORDS:
        kw_clean = kw.strip()
        kw_words = kw_clean.split()
        if len(kw_words) > 1:
            if kw_clean in text_clean:
                scores['disappointed'] += 2
        elif kw_clean in clean_words:
            scores['disappointed'] += 2

    for kw in CONFUSED_KEYWORDS:
        kw_clean = kw.strip().rstrip('?')
        kw_words = kw_clean.split()
        if len(kw_words) > 1:
            if kw_clean in text_clean:
                scores['confused'] += 2
        elif kw_clean in clean_words:
            scores['confused'] += 2

    for kw in EXCITED_KEYWORDS:
        kw_clean = kw.strip()
        kw_words = kw_clean.split()
        if len(kw_words) > 1:
            if kw_clean in text_clean:
                scores['excited'] += 2
        elif kw_clean in clean_words:
            scores['excited'] += 2

    if '?' in text_lower and scores['confused'] == 0 and scores['angry'] == 0 and scores['disappointed'] == 0:
        scores['confused'] += 0.5

    if '!' in text_lower:
        top_emotion = max(scores, key=scores.get)
        if top_emotion in ('happy', 'excited') and scores[top_emotion] > 0:
            scores[top_emotion] += 1
        elif top_emotion == 'angry' and scores['angry'] > 0:
            scores['angry'] += 1

    for negation in ['not', "n't", 'no']:
        if negation in clean_words:
            for pw in ['good', 'great', 'fine', 'happy', 'better', 'well']:
                if pw in clean_words:
                    scores['disappointed'] += 1
                    scores['happy'] = max(0, scores['happy'] - 1)

    if all(v == 0 for v in scores.values()):
        return 'neutral'

    winner = max(scores, key=scores.get)
    return winner

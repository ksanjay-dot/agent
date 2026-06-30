from datetime import date, datetime, timedelta, timezone

FESTIVALS_2026 = [
    {"name": "Makar Sankranti / Pongal", "date": date(2026, 1, 14), "days_before": 3},
    {"name": "Republic Day", "date": date(2026, 1, 26), "days_before": 2},
    {"name": "Vasant Panchami", "date": date(2026, 1, 23), "days_before": 2},
    {"name": "Valentine's Day", "date": date(2026, 2, 14), "days_before": 4},
    {"name": "Maha Shivaratri", "date": date(2026, 2, 15), "days_before": 3},
    {"name": "Holi", "date": date(2026, 3, 4), "days_before": 5},
    {"name": "Eid ul-Fitr", "date": date(2026, 3, 20), "days_before": 3},
    {"name": "Gudi Padwa / Ugadi", "date": date(2026, 3, 19), "days_before": 2},
    {"name": "Good Friday", "date": date(2026, 4, 3), "days_before": 2},
    {"name": "Easter", "date": date(2026, 4, 5), "days_before": 3},
    {"name": "Baisakhi / Vishu", "date": date(2026, 4, 14), "days_before": 2},
    {"name": "Eid al-Adha", "date": date(2026, 5, 28), "days_before": 3},
    {"name": "Mother's Day", "date": date(2026, 5, 10), "days_before": 4},
    {"name": "Father's Day", "date": date(2026, 6, 21), "days_before": 4},
    {"name": "Rath Yatra", "date": date(2026, 7, 14), "days_before": 2},
    {"name": "Friendship Day", "date": date(2026, 8, 2), "days_before": 3},
    {"name": "Raksha Bandhan", "date": date(2026, 8, 28), "days_before": 4},
    {"name": "Janmashtami", "date": date(2026, 9, 5), "days_before": 3},
    {"name": "Ganesh Chaturthi", "date": date(2026, 9, 15), "days_before": 4},
    {"name": "Diwali", "date": date(2026, 10, 17), "days_before": 7},
    {"name": "Dhanteras", "date": date(2026, 10, 15), "days_before": 3},
    {"name": "Bhai Dooj", "date": date(2026, 10, 19), "days_before": 2},
    {"name": "Christmas", "date": date(2026, 12, 25), "days_before": 7},
    {"name": "New Year's Eve", "date": date(2026, 12, 31), "days_before": 5},
]

BUSINESS_FESTIVAL_MAP = {
    "cafe": ["Valentine's Day", "Friendship Day", "New Year's Eve", "Weekend"],
    "restaurant": ["Valentine's Day", "Friendship Day", "New Year's Eve", "Weekend", "Holi", "Diwali", "Christmas"],
    "bakery": ["Christmas", "New Year's Eve", "Diwali", "Easter", "Holi"],
    "salon": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Eid ul-Fitr"],
    "spa": ["Valentine's Day", "Mother's Day", "New Year's Eve", "Diwali"],
    "gym": ["New Year's Eve", "Republic Day", "Good Friday"],
    "clinic": ["Good Friday", "Holi", "Diwali"],
    "dental": ["Good Friday", "Holi", "Diwali"],
    "hospital": [],
    "event": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Friendship Day", "Valentine's Day"],
    "entertainment": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Weekend", "Friendship Day"],
    "movie": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Weekend", "Friendship Day"],
    "store": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Dhanteras", "Raksha Bandhan"],
    "jewelry": ["Dhanteras", "Diwali", "Raksha Bandhan", "New Year's Eve", "Valentine's Day"],
    "electronics": ["Dhanteras", "Diwali", "New Year's Eve", "Christmas"],
    "fashion": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Raksha Bandhan"],
    "fitness": ["New Year's Eve", "Republic Day", "Good Friday"],
    "travel": ["Holi", "Diwali", "Christmas", "New Year's Eve", "Good Friday"],
    "hotel": ["Christmas", "New Year's Eve", "Holi", "Diwali", "Weekend"],
    "default": ["Holi", "Diwali", "Christmas", "New Year's Eve"],
}

VARIED_SEQUENCE_DAYS = {
    0: 1,
    1: 4,
    4: 10,
    10: 18,
    18: 28,
    28: 30,
}

WEEKEND_BUSINESS_TYPES = {
    "cafe", "restaurant", "bakery", "hotel", "entertainment",
    "movie", "event", "salon", "spa",
}


def get_upcoming_festivals(business_type=None, days_ahead=14):
    today = date.today()
    relevant = []

    for f in FESTIVALS_2026:
        if f["date"] >= today:
            days_until = (f["date"] - today).days
            if days_until <= days_ahead + f["days_before"]:
                if business_type:
                    biz_fests = BUSINESS_FESTIVAL_MAP.get(
                        business_type.lower(), BUSINESS_FESTIVAL_MAP["default"]
                    )
                    if f["name"] not in biz_fests:
                        continue
                relevant.append({**f, "days_until": days_until})

    relevant.sort(key=lambda x: x["days_until"])
    return relevant


def is_weekend_approach(days_ahead=3):
    today = date.today()
    weekday = today.weekday()
    for offset in range(days_ahead):
        check = today + timedelta(days=offset)
        if check.weekday() >= 5:
            return True, offset, check.strftime("%A")
    return False, None, None


def is_friday():
    return date.today().weekday() == 4


def get_next_sequence_day_varied(current_day):
    if current_day in VARIED_SEQUENCE_DAYS:
        return VARIED_SEQUENCE_DAYS[current_day]
    return "completed"


def should_send_weekend_message(business_type):
    if not business_type:
        return False
    return business_type.lower() in WEEKEND_BUSINESS_TYPES


def get_festival_message_context(business, customer):
    business_type = (business.get("business_type") or "").lower()
    festivals = get_upcoming_festivals(business_type, days_ahead=14)

    context = []
    for f in festivals[:2]:
        if f["days_until"] <= f["days_before"]:
            context.append(f)

    if not context:
        return None

    return {
        "primary": context[0],
        "secondary": context[1] if len(context) > 1 else None,
        "is_weekend": is_weekend_approach()[0],
    }

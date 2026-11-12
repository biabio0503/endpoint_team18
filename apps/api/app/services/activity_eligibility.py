"""Pure shared KST registration and undergraduate eligibility rules."""
from datetime import date, datetime, time
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DATE = r'(?:(?P<year>20\d{2})\s*[.\-/년]\s*)?(?P<month>\d{1,2})\s*[.\-/월]\s*(?P<day>\d{1,2})(?:\s*[.일])?'
POINT = re.compile(r'^' + DATE + r'(?:\s*\([월화수목금토일](?:요일)?\))?(?:\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2})|시(?:\s*(?P<kminute>\d{1,2})분)?))?\s*$')
ALWAYS = {'상시', '상시접수', '상시모집', '연중상시', '연중상시접수', '연중접수'}


def period_status(value, now):
    """Require a year anchor. An omitted end year can roll into the next year."""
    value = value.strip()
    if re.sub(r'\s+', '', value) in ALWAYS:
        return {'status': 'open', 'deadline': None, 'deadline_label': '상시 접수', 'opens_at': None, 'closes_at': None}
    parts = re.split(r'\s*(?:~|～|∼|–|부터)\s*', value)
    if len(parts) != 2:
        return {'status': 'unknown'}
    matches = [POINT.fullmatch(re.sub(r'까지$', '', p).strip()) for p in parts]
    if not all(matches):
        return {'status': 'unknown'}
    a, b = [m.groupdict() for m in matches]
    if not a['year'] and not b['year']:
        return {'status': 'unknown'}
    try:
        am, ad, bm, bd = (int(a['month']), int(a['day']), int(b['month']), int(b['day']))
        ay = int(a['year'] or b['year'])
        by = int(b['year'] or a['year'])
        if not b['year'] and (bm, bd) < (am, ad):
            by += 1
        if not a['year'] and (am, ad) > (bm, bd):
            ay -= 1
        start_date, end_date = date(ay, am, ad), date(by, bm, bd)
        start_time = time(int(a['hour'] or 0), int(a['minute'] or a['kminute'] or 0))
        end_time = time(int(b['hour']), int(b['minute'] or b['kminute'] or 0)) if b['hour'] else time.max
        start, end = datetime.combine(start_date, start_time, KST), datetime.combine(end_date, end_time, KST)
        if end < start:
            raise ValueError
    except ValueError:
        return {'status': 'unknown'}
    return {'status': 'upcoming' if now < start else 'closed' if now > end else 'open',
            'deadline': end_date.isoformat(), 'opens_at': start.isoformat(), 'closes_at': end.isoformat(),
            'deadline_label': end_date.isoformat() + (f' {end_time:%H:%M} (한국 시간)' if b['hour'] else ' (한국 시간, 당일 포함)')}


def eligible_target(value):
    # Lists with additional conditions (e.g. 해당자, 지역/학년 제한, 제외) are ambiguous.
    tokens = [t.strip() for t in re.split(r'[,/·ㆍ•|\n]', value) if t.strip()]
    known = {'누구나', '대학생', '대학원생', '일반인', '외국인', '유치원', '초등학생', '중학생', '고등학생'}
    return bool(set(tokens) & {'대학생', '누구나'}) and all(t in known for t in tokens)


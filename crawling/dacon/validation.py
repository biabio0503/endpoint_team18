"""Validate public evidence before publishing a complete daily snapshot.

Unknown application dates/eligibility stay unknown: competition dates never fill
application dates. Ineligible or unverified records are stored but not recommended.
"""
from datetime import datetime, time
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
POINT = r'20\d{2}\s*[./년-]\s*\d{1,2}\s*[./월-]\s*\d{1,2}(?:일|\.)?(?:\s*\([월화수목금토일](?:요일)?\))?(?:\s+\d{1,2}(?::\d{2}|시(?:\s*\d{1,2}분)?))?'
RANGE = re.compile(r'(' + POINT + r')\s*(?:~|～|∼|–|—|부터)\s*(' + POINT + r')')
APPLICATION = re.compile(r'^[\s\[•·-]*(?:(?:참가|참여)\s*(?:신청|접수|등록)(?:서\s*제출)?(?:\s*기간)?|신청\s*기간|접수\s*기간|모집\s*기간)\s*[:：\]]?\s*(?=$|20\d{2}|\d{1,2}/)')
TARGET = re.compile(r'^[\[\s#]*(?:참가|참여|신청|모집)\s*(?:대상|자격)\s*[\]:：]?')
SHORT_RANGE = re.compile(r'(?<![\d.])(?P<am>\d{1,2})/(?P<ad>\d{1,2})\s+(?P<ah>\d{1,2}):(?P<an>\d{2})\s*~\s*(?P<bm>\d{1,2})/(?P<bd>\d{1,2})\s+(?P<bh>\d{1,2}):(?P<bn>\d{2})(?!\d)')


def parse_point(value, end=False):
    parts = list(map(int, re.findall(r'\d+', value)))
    clock = time(parts[3], parts[4] if len(parts) > 4 else 0) if len(parts) > 3 else (time.max if end else time.min)
    return datetime(parts[0], parts[1], parts[2], clock.hour, clock.minute, clock.second, clock.microsecond, KST)


def extract_evidence(text, calendar_bounds=None):
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    periods, targets, evidence, precision = {}, [], {}, {}
    for i, line in enumerate(lines):
        # Bounded block: do not let a nearby competition/submission period stand
        # in for registration. Stop at the next labelled section/date range.
        block = [line]
        for following in lines[i + 1:i + 4]:
            if re.search(r'(?:대회|평가|제출|심사|발표)\s*(?:기간|일정)|^(?:참가|참여)\s*(?:대상|자격)', following):
                break
            block.append(following)
            if RANGE.search(following) or SHORT_RANGE.search(following):
                break
        quote = '\n'.join(block)
        if APPLICATION.search(line):
            for found in RANGE.finditer(quote):
                try:
                    start, end = parse_point(found[1]), parse_point(found[2], end=True)
                    if end >= start:
                        key = start.isoformat(), end.isoformat()
                        periods[key], evidence[key] = found[0], quote
                        precision[key] = 'time' if len(re.findall(r'\d+', found[2])) > 3 else 'date'
                except ValueError:
                    pass
            # Daker displays month/day on its explicitly labelled registration
            # stage and full years on that page's schedule. Use that year anchor
            # only when there is exactly one valid interpretation in the schedule.
            if calendar_bounds and not RANGE.search(quote):
                lo, hi = (datetime.fromisoformat(v).date() for v in calendar_bounds)
                for found in SHORT_RANGE.finditer(quote):
                    interpretations = []
                    for year in range(lo.year, hi.year + 1):
                        try:
                            start = datetime(year, int(found['am']), int(found['ad']), int(found['ah']), int(found['an']), tzinfo=KST)
                            end_year = year + (int(found['bm']) < int(found['am']))
                            end = datetime(end_year, int(found['bm']), int(found['bd']), int(found['bh']), int(found['bn']), tzinfo=KST)
                            if lo <= start.date() <= end.date() <= hi and start <= end:
                                interpretations.append((start.isoformat(), end.isoformat()))
                        except ValueError:
                            pass
                    if len(interpretations) == 1:
                        key = interpretations[0]
                        periods[key], evidence[key] = found[0], quote + '\n연도 근거: ' + ' ~ '.join(calendar_bounds)
                        precision[key] = 'time'
        if TARGET.search(line):
            value = TARGET.sub('', line, count=1).strip(' :：[]【】-')
            following = []
            for next_line in lines[i + 1:i + 5]:
                if re.search(r'^(?:\[|#|\d+[.)]|주제|일정|기간|상금|평가|신청|접수|대회|참가\s*방법)', next_line):
                    break
                following.append(next_line)
            targets.append('\n'.join(([value] if value else []) + following).strip())
    # Keep the full eligibility quote. Only exact unqualified statements qualify.
    target = '\n'.join(dict.fromkeys(v for v in targets if v))
    normalized = re.sub(r'^[\s•·\-]+', '', target).strip()
    if re.fullmatch(r'(?:(?:데이터\s*분석|인공지능|AI|해커톤)(?:에\s*관심\s*있는)?\s*(?:분야에\s*관심\s*있는\s*)?|일반인,\s*학생\s*등\s*)?누구나(?:\s*대회\s*참가\s*가능)?[.!]?', normalized, re.I):
        normalized = '누구나'
    result = {'application_start_at': None, 'application_end_at': None,
              'application_period': None, 'application_evidence': None,
              'application_cancelled': any(re.fullmatch(r'(?:대회|행사|접수|모집)(?:이|가)?\s*취소(?:되었습니다|되었어요|됨)?[.!]?', line) for line in lines),
              'application_closed': any(re.fullmatch(r'(?:참가\s*)?(?:신청|접수)(?:이|가)?\s*(?:마감|종료)(?:되었습니다|되었어요|됨)?[.!]?', line) for line in lines),
              'eligibility_text': target or None, 'target': normalized}
    if len(periods) == 1:
        (start, end), period = next(iter(periods.items()))
        result.update(application_start_at=start, application_end_at=end,
                      application_period=period, application_evidence=evidence[(start, end)],
                      application_end_precision=precision[(start, end)])
    return result


def validate_records(records):
    if not isinstance(records, list):
        raise ValueError('invalid_collection')
    found = {}
    for raw in records:
        item = dict(raw)
        legacy_id = str(item.get('id', ''))
        source = item.get('source') or ('daker' if legacy_id.startswith('daker:') else 'dacon')
        original_id = item.get('original_id') or legacy_id.removeprefix('daker:')
        parsed = urlsplit(item.get('url', ''))
        pattern = rf'/public/hackathons/{re.escape(original_id)}/?' if source == 'daker' else rf'/(?:competitions/(?:official|open)|competition)/{re.escape(original_id)}(?:/[^?#]*)?'
        if (source not in ('dacon', 'daker') or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', original_id)
                or parsed.scheme != 'https' or parsed.hostname != {'dacon': 'dacon.io', 'daker': 'daker.ai'}[source]
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(pattern, parsed.path) or not str(item.get('title', '')).strip()
                or item.get('status') not in ('진행중', '모집중', '접수예정', '종료', '마감', '연습', 'unknown', 'conflict')):
            raise ValueError('invalid_record')
        for field in ('application_start_at', 'application_end_at'):
            if item.get(field):
                stamp = datetime.fromisoformat(item[field])
                if stamp.tzinfo is None:
                    raise ValueError('timezone_required')
        if bool(item.get('application_start_at')) != bool(item.get('application_end_at')):
            raise ValueError('incomplete_application_period')
        if item.get('application_start_at'):
            if (not item.get('application_evidence') or not item.get('application_period')
                    or datetime.fromisoformat(item['application_end_at']) < datetime.fromisoformat(item['application_start_at'])):
                raise ValueError('invalid_application_evidence')
        item.update(source=source, original_id=original_id, id=f'{source}:{original_id}')
        key = source, original_id
        if key in found and found[key] != item:
            raise ValueError('conflicting_duplicate')
        found[key] = item
    return list(found.values())

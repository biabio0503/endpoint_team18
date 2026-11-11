"""Conservative, extractive activity and contribution checks over saved source spans.

Geometry is local to a PDF page or an embedded image's paragraph. Text order is
never a substitute for geometry. Without geometry only explicit table rows or
an uninterrupted list under a personal-work heading establish context.
"""
import math
import re

from services.job_skill_analysis import _skill_in_quote


PERSONAL = re.compile(r'\bI\s|\bmy\s|나는|내가|제가|저는|본인은|본인이', re.I)
TEAM = re.compile(r'팀원\s*담당|팀\s*(?:전체|담당|수행|에서는|은|이)|\b(?:we|our team)\b', re.I)
NEGATIVE = re.compile(r'미수행|미사용|미구현|미참여|수행하지\s*않|사용하지\s*않|구현하지\s*않')
ACTION = re.compile(r'설계|구현|작성|파싱|연동|사용(?:했|하|하여|한|함|해|$|[\s.,])|구성|설정|개발|배포|운영|구축|처리|분석|전처리|'
                    r'\b(?:used?|built|implemented|designed|wrote|created|developed|configured|deployed|analy[sz]ed)\b', re.I)
NON_WORK = re.compile(r'예정|계획|튜토리얼|요구\s*사항|사용\s*목록|기술\s*목록|라이브러리\s*목록|\b(?:planned|tutorial|requirements?)\b', re.I)
PERSONAL_HEADING = re.compile(r'^(?:\d+[.)]\s*)?본인이\s*직접\s*수행한\s*작업\s*[:：]?$')
CONTRIBUTION_HEADER = re.compile(r'^본인\s*기여\s*여부$')
TECH_HEADER = re.compile(r'^기술\s*스택$')
ROW_LABEL = re.compile(r'^(?:직접\s*(?:사용|구현|설계)|일부\s*설정|팀원\s*담당|미수행)$')


def names_skill(name, text):
    return _skill_in_quote(name, re.sub(r'(?<=[A-Za-z0-9])(?=[가-힣])', ' ', text))


def clean(text):
    return re.sub(r'^(?:\s*[-*•●▪]\s*|\s*#+\s*|\s*\d+[.)]\s+)', '', text).strip()


def performed(text):
    return bool(ACTION.search(text)) and not NON_WORK.search(text)


def rectangle(segment):
    box = segment.get('bbox')
    if not isinstance(box, (list, tuple)) or len(box) < 2:
        return None
    try:
        if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
            x0, y0, x1, y1 = box
        else:
            x0, x1 = min(p[0] for p in box), max(p[0] for p in box)
            y0, y1 = min(p[1] for p in box), max(p[1] for p in box)
        if all(math.isfinite(v) for v in (x0, y0, x1, y1)) and x1 > x0 and y1 > y0:
            return x0, y0, x1, y1
    except (TypeError, ValueError, IndexError):
        pass
    return None


def space(segment):
    # DOCX images have paragraph-relative coordinates; separate images must not mix.
    return (segment.get('page'), segment.get('paragraph'), segment.get('image_ref'))


def same_row(left, right):
    a, b = left['box'], right['box']
    return (left['space'] == right['space'] and
            min(a[3], b[3]) - max(a[1], b[1]) >= .6 * max(a[3] - a[1], b[3] - b[1]))


class EvidenceIndex:
    def __init__(self, document):
        self.text = document['extracted_text']
        self.segments = document.get('segments') or []
        self.cells = []
        for segment in self.segments:
            start, end = segment.get('start'), segment.get('end')
            box = rectangle(segment)
            if (box and space(segment)[:2] != (None, None) and isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end <= len(self.text)):
                self.cells.append({'start': start, 'end': end, 'text': self.text[start:end],
                                   'box': box, 'space': space(segment)})
        self.lines = [{'start': m.start(), 'end': m.end(), 'text': m.group()}
                      for m in re.finditer(r'[^\n]+', self.text)]

    def span(self, unit, kind):
        start, end = unit['start'], unit['end']
        return {'kind': kind, 'text': self.text[start:end], 'start': start, 'end': end,
                'locations': self.locations(start, end)}

    def locate(self, quote):
        # Prefer an exact cell/line over a technology substring in another sentence.
        exact = {c['start'] + c['text'].find(quote) for c in self.cells + self.lines
                 if c['text'].strip() == quote.strip() and quote in c['text']}
        if exact:
            return min(exact), len(exact) > 1
        start = self.text.find(quote)
        return start, start >= 0 and self.text.find(quote, start + 1) >= 0

    def locations(self, start, end):
        return [s for s in self.segments if s.get('start', end) < end and s.get('end', start) > start]

    def table_geometry(self, cell):
        matches = []
        for header in self.cells:
            if not CONTRIBUTION_HEADER.fullmatch(clean(header['text'])) or header['space'] != cell['space']:
                continue
            tech_headers = [h for h in self.cells if TECH_HEADER.fullmatch(clean(h['text']))
                            and same_row(h, header) and h['box'][2] < header['box'][0]]
            if len(tech_headers) != 1:
                continue
            tech_header = tech_headers[0]
            height = header['box'][3] - header['box'][1]
            def in_tech_column(c):
                return (c['space'] == header['space'] and c['box'][1] > header['box'][3]
                        and c['box'][0] >= tech_header['box'][0] - height
                        and c['box'][2] < header['box'][0])
            if not in_tech_column(cell):
                continue
            labels = [c for c in self.cells if c['space'] == header['space']
                      and abs(c['box'][0] - header['box'][0]) <= height
                      and ROW_LABEL.fullmatch(clean(c['text'])) and same_row(c, cell)]
            if len(labels) != 1:
                continue
            label = labels[0]
            # A tall/merged cell or overlapping rows cannot establish a unique row.
            if sum(in_tech_column(c) and same_row(c, label) for c in self.cells) != 1:
                continue
            rows = sorted([c for c in self.cells if in_tech_column(c)
                           and c['box'][1] <= cell['box'][1]], key=lambda c: c['box'][1])
            previous = tech_header
            connected = True
            for row in rows:
                if (row['box'][1] - previous['box'][3] > 3 * height
                        or not any(ROW_LABEL.fullmatch(clean(c['text'])) and same_row(row, c)
                                   and abs(c['box'][0] - header['box'][0]) <= height for c in self.cells)):
                    connected = False
                    break
                previous = row
            if connected:
                matches.append((clean(label['text']), [self.span(tech_header, 'technology_header'),
                    self.span(header, 'contribution_header'), self.span(cell, 'technology_cell'),
                    self.span(label, 'contribution_cell')], 'table_bbox'))
        return matches[0] if len(matches) == 1 else None

    def table_text(self, start, end):
        # Delimited rows only. Column-major OCR and bare adjacent words are ambiguous.
        headers = None
        previous_end = 0
        for line in self.lines:
            if re.search(r'\n\s*\n', self.text[previous_end:line['start']]):
                headers = None
            previous_end = line['end']
            separators = list(re.finditer(r'\||\t| {2,}', line['text']))
            ranges = zip([0] + [m.end() for m in separators],
                         [m.start() for m in separators] + [len(line['text'])]) if separators else []
            cells = []
            for left, right in ranges:
                part = line['text'][left:right]
                if part.strip():
                    a = line['start'] + left + len(part) - len(part.lstrip())
                    b = line['start'] + right - (len(part) - len(part.rstrip()))
                    cells.append({'start': a, 'end': b, 'text': self.text[a:b]})
            if not cells:
                headers = None
                continue
            names = [clean(c['text']) for c in cells]
            if '기술 스택' in names and '본인 기여 여부' in names:
                headers = (cells, names.index('기술 스택'), names.index('본인 기여 여부'))
                continue
            if all(re.fullmatch(r'[-: ]+', n) for n in names):
                continue
            if not headers or len(cells) != len(headers[0]):
                headers = None
                continue
            hs, ti, ci = headers
            tech, label = cells[ti], cells[ci]
            if not ROW_LABEL.fullmatch(clean(label['text'])):
                headers = None
                continue
            if start < tech['end'] and end > tech['start']:
                return clean(label['text']), [self.span(hs[ti], 'technology_header'),
                    self.span(hs[ci], 'contribution_header'), self.span(tech, 'technology_cell'),
                    self.span(label, 'contribution_cell')], 'table_row'
        return None

    def section(self, unit, positioned):
        units = (sorted([c for c in self.cells if c['space'] == unit['space']],
                        key=lambda c: (c['box'][1], c['box'][0])) if positioned else self.lines)
        heading = None
        previous = None
        for entry in units:
            text = clean(entry['text'])
            if PERSONAL_HEADING.fullmatch(text):
                heading = entry
            elif heading:
                # A new title, table, team section, or non-list paragraph ends the section.
                boundary = (not performed(text) and not NEGATIVE.search(text)) or bool(
                    re.search(r'[:：]|^#{1,6}\s|^팀\s*전체', entry['text']))
                if positioned:
                    h = heading['box']
                    boundary |= (not h[0] - 5 <= entry['box'][0] <= h[0] + 3 * (h[3] - h[1])
                                 or entry['box'][1] < h[3]
                                 or (previous is not None and entry['box'][1] - previous['box'][3] > 3 * (h[3] - h[1])))
                elif previous and re.search(r'\n\s*\n', self.text[previous['end']:entry['start']]):
                    boundary = True
                if boundary:
                    heading = None
            if entry['start'] == unit['start'] and entry['end'] == unit['end']:
                return ([self.span(heading, 'personal_section')] if heading and heading != entry else [])
            previous = entry
        return []

    def resolve(self, name, start, end):
        quote = self.text[start:end]
        positioned = [c for c in self.cells if c['start'] < end and c['end'] > start
                      and names_skill(name, c['text'])]
        # If coordinates exist for the quote, never fall back to flat reading order.
        has_geometry = any(c['start'] < end and c['end'] > start for c in self.cells)
        units = positioned if has_geometry else [l for l in self.lines if l['start'] < end and l['end'] > start
                                                 and names_skill(name, l['text'])]
        if len(units) != 1:
            return None
        unit = units[0]
        a, b = max(start, unit['start']), min(end, unit['end'])
        local = self.text[a:b].strip()
        table = self.table_geometry(unit) if has_geometry else self.table_text(a, b)
        context, method, label = [], 'quote', ''
        if table:
            label, context, method = table
        else:
            context = self.section(unit, has_geometry)
            if context:
                method = 'section_bbox' if has_geometry else 'section_list'
        # Only source language can become an activity. Never preserve a fluent but
        # unverifiable model paraphrase (quantities, leadership, or inflated scope).
        ambiguous_table = not table and not context and any(
            re.search(r'본인\s*기여\s*여부', c['text']) for c in (self.cells if has_geometry else self.lines))
        flattened_rows = not table and not has_geometry and (
            '본인 기여 여부' in local or len(re.findall(
                r'직접\s*(?:사용|구현|설계)|일부\s*설정|팀원\s*담당|미수행', local)) > 1)
        ambiguous_table |= flattened_rows
        if flattened_rows:
            activity = name + ' · 수행 내용 미확인'
        elif performed(local) or NEGATIVE.search(local) or TEAM.search(local):
            activity = clean(local)
        elif label:
            activity = clean(local) + ' · ' + label
        elif ambiguous_table:
            # A technology in an unresolved table is a mention, not performed work.
            activity = clean(local)
        else:
            return None
        actor_text = '' if flattened_rows else local + ' ' + label
        if NEGATIVE.search(actor_text):
            scope, reason = 'unknown', 'not_performed'
        elif TEAM.search(actor_text):
            scope, reason = 'team', 'explicit_team'
        elif not flattened_rows and (table or context or PERSONAL.search(local)):
            scope, reason = 'personal', 'document_personal'
        else:
            scope, reason = 'unknown', 'ambiguous_table_row' if ambiguous_table else 'actor_unspecified'
        # Repeated identical quotations have no unique model-supplied location.
        if self.locate(quote)[1]:
            scope, reason, context, method = 'unknown', 'ambiguous_source_location', [], 'quote'
        return {'activity': activity, 'contribution_scope': scope,
                'contribution_basis': {'source': 'document', 'method': method, 'reason': reason,
                                       'context': context}}

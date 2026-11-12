"""Conservative, extractive activity and contribution checks over saved source spans.

Geometry is local to a PDF page or an embedded image's paragraph. Text order is
never a substitute for geometry. Without geometry only explicit table rows or
an uninterrupted list under a personal-work heading establish context.
"""
import math
import re

from services.job_skill_analysis import _key, _skill_in_quote


PERSONAL = re.compile(r'\bI\s|\bmy\s|나는|내가|제가|저는|본인은|본인이', re.I)
TEAM = re.compile(r'팀원\s*담당|팀원\s+[가-힣A-Za-z]+(?:은|는|이|가)(?=\s)|'
                  r'팀\s*(?:전체|담당|수행|에서는|은|이)|\b(?:we|our team)\b', re.I)
WORK_VERB = r'(?:수행|사용|구현|참여|설계|작성|파싱|연동|구성|설정|개발|배포|운영|구축|처리|분석|전처리|제작|진행|기록|정리)'
NEGATIVE = re.compile(
    r'미수행|미사용|미구현|미참여|(?:' + WORK_VERB + r'(?:하|해\s*보)|만들|만들어\s*보)지\s*(?:않|못)|'
    r'(?:' + WORK_VERB + r'(?:한|해\s*본)|만든|만들어\s*본)\s*(?:적|경험)(?:이|은|도)?\s*없')
# Keep the predicate in its clause. Splitting at arbitrary negative words would
# also reject completed work describing a participant's problem (찾지 못하는).
# Do not split noun lists: multiple technologies can share one denied predicate.
ACTIVITY_CLAUSE_END = re.compile(
    r'(?:' + WORK_VERB + r'(?:했(?:지만|으나|고|으며|는데)|하(?:지만|고|며|여)|해(?:서)?)|'
    r'만들(?:었(?:지만|으나|고|으며|는데)|어(?:서)?|고|며)|'
    r'(?:않|없)(?:았|었)?(?:지만|고|으며|는데)|못했(?:지만|고|으며|는데))'
    r'(?=\s|[,.;!?]|$)|[.!?](?=\s|$)')
ACTION = re.compile(r'설계|구현|작성|파싱|연동|사용(?:했|하|하여|한|함|해|$|[\s.,])|구성|설정|개발|배포|운영|구축|처리|분석|전처리|'
                    r'만들(?:었|어|고|기|지)|제작|진행|기록|정리|'
                    r'\b(?:used?|built|implemented|designed|wrote|created|developed|configured|deployed|analy[sz]ed)\b', re.I)
NON_WORK = re.compile(r'예정|계획|튜토리얼|요구\s*사항|사용\s*목록|기술\s*목록|라이브러리\s*목록|\b(?:planned|tutorial|requirements?)\b', re.I)
PERSONAL_HEADING = re.compile(r'^(?:\d+[.)]\s*)?본인이\s*직접\s*수행한\s*작업\s*[:：]?$')
CONTRIBUTION_HEADER = re.compile(r'^본인\s*기여\s*여부$')
TECH_HEADER = re.compile(r'^기술\s*스택$')
ROW_LABEL = re.compile(r'^(?:직접\s*(?:사용|구현|설계)|일부\s*설정|팀원\s*담당|미수행)$')
ROLE_DESCRIPTION = re.compile(r'^담당\s*역할\s*[:：]\s*\S')
NUMBERED = re.compile(r'^\s*(\d+)[.)]\s+')
# Match text_cells' explicit delimiters even when OCR merges cells into one box.
# Coordinates do not make an actor in an adjacent cell valid evidence.
SOURCE_CELL_BREAK = re.compile(r'[\n|\t]| {2,}')


def names_skill(name, text):
    if _skill_in_quote(name, re.sub(r'(?<=[A-Za-z0-9])(?=[가-힣])', ' ', text)):
        return True
    # Korean activity names take attached particles too. Keep both word boundaries
    # so 사용자 인터뷰를 matches, but 사용자 인터뷰어 / 비사용자 인터뷰 do not.
    if re.search(r'[가-힣]$', name.strip()):
        return bool(re.search(r'(?<!\w)' + re.escape(_key(name)) +
            r'(?:으로부터|에서|으로|에게|에는|은|는|이|가|을|를|과|와|로|도|만)?(?!\w)', _key(text)))
    return False


def clean(text):
    return re.sub(r'^(?:\s*[-*•●▪①-⑳]\s*|\s*#+\s*|\s*\d+[.)]\s+)', '', text).strip()


def performed(text):
    return bool(ACTION.search(text)) and not NON_WORK.search(text)


def negates_skill(name, text):
    # A model may cite the same whole sentence for several activities. Only the
    # clause naming this candidate can deny it; other clauses remain in the quote.
    start = 0
    negatives = list(NEGATIVE.finditer(text))
    if not negatives:
        return False
    # 진행해 본 적이 없다 / 만들어 본 적이 없다 are single negative predicates.
    barriers = {m.end() for m in SOURCE_CELL_BREAK.finditer(text)}
    ends = sorted({m.end() for m in ACTIVITY_CLAUSE_END.finditer(text)
                   if not any(n.start() < m.end() < n.end() for n in negatives)} | barriers | {len(text)})
    for end in ends:
        clause = text[start:end]
        if names_skill(name, clause) and NEGATIVE.search(clause):
            return True
        start = end
    return False


def source_clause(name, text, quote_start, quote_end):
    """Resolve only the candidate's clause, carrying an omitted subject forward.

    Callers bound text to one source line/cell. A subject never travels backwards,
    across a sentence, or through a new explicit subject. Unresolved/multiple
    occurrences stay unknown instead of trusting the model's personal label.
    """
    negatives = list(NEGATIVE.finditer(text))
    barriers = {m.end() for m in SOURCE_CELL_BREAK.finditer(text)}
    ends = sorted({m.end() for m in ACTIVITY_CLAUSE_END.finditer(text)
                   if not any(n.start() < m.end() < n.end() for n in negatives)} | barriers | {len(text)})
    start, inherited, matches = 0, None, []
    for end in ends:
        clause = text[start:end]
        predicates = [m.start() for pattern in (ACTION, NEGATIVE) if (m := pattern.search(clause))]
        subject_text = clause[:min(predicates)] if predicates else clause
        personal, team = bool(PERSONAL.search(subject_text)), bool(TEAM.search(clause))
        # Technology topics ("Docker는") are not people. An unidentified named
        # subject ("민수는") must not inherit a student's previous contribution.
        subjects = re.findall(r'(?<!\w)(?:담당자\s+)?[가-힣A-Za-z]+(?:은|는|이|가)(?=\s)', subject_text)
        other = any(not PERSONAL.search(s) and not team and not names_skill(name, s)
                    for s in subjects)
        actor = ('unknown' if personal and team or personal and other else
                 'team' if team else 'personal' if personal else 'unknown' if other else inherited)
        if names_skill(name, text[max(start, quote_start):min(end, quote_end)]) and start < quote_end and end > quote_start:
            matches.append((clause.strip(), actor))
        inherited = None if end in barriers or re.search(r'[.!?]\s*$', clause) else actor
        start = end
    if len(matches) == 1:
        return matches[0]
    return text.strip(), 'unknown'


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
        self._table_membership = {}

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
                      and clean(c['text']) and same_row(c, cell)]
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
                        or not any(clean(c['text']) and same_row(row, c)
                                   and abs(c['box'][0] - header['box'][0]) <= height for c in self.cells)):
                    connected = False
                    break
                previous = row
            if connected:
                matches.append((clean(label['text']), [self.span(tech_header, 'technology_header'),
                    self.span(header, 'contribution_header'), self.span(cell, 'technology_cell'),
                    self.span(label, 'contribution_cell')], 'table_bbox'))
        return matches[0] if len(matches) == 1 else None

    def text_cells(self, line):
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
        return cells

    def text_table_rows(self):
        """Yield only rows inside an uninterrupted, explicitly delimited table."""
        headers = None
        previous_end = 0
        for line in self.lines:
            if re.search(r'\n\s*\n', self.text[previous_end:line['start']]):
                headers = None
            previous_end = line['end']
            cells = self.text_cells(line)
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
            yield headers, cells

    def table_text(self, start, end):
        # Column-major OCR and bare adjacent words never establish a specific row.
        for headers, cells in self.text_table_rows():
            hs, ti, ci = headers
            tech, label = cells[ti], cells[ci]
            if start < tech['end'] and end > tech['start']:
                return clean(label['text']), [self.span(hs[ti], 'technology_header'),
                    self.span(hs[ci], 'contribution_header'), self.span(tech, 'technology_cell'),
                    self.span(label, 'contribution_cell')], 'table_row'
        return None

    def in_table(self, unit, positioned):
        """Table membership is distinct from proving a particular row's actor."""
        key = (unit['start'], unit['end'], positioned)
        if key not in self._table_membership:
            self._table_membership[key] = self._in_table(unit, positioned)
        return self._table_membership[key]

    def _in_table(self, unit, positioned):
        if positioned:
            peers = [c for c in self.cells if c['space'] == unit['space']]
            for header in peers:
                if not TECH_HEADER.fullmatch(clean(header['text'])):
                    continue
                x, y, right, bottom = header['box']
                height = bottom - y
                if unit['box'][1] <= bottom or unit['box'][0] < x - height:
                    continue
                contribution_headers = [c for c in peers if CONTRIBUTION_HEADER.fullmatch(clean(c['text']))
                                        and same_row(c, header) and c['box'][0] > right]
                labels = [c for c in peers if c['box'][0] > right and c['box'][1] > bottom and (
                    abs(c['box'][0] - contribution_headers[0]['box'][0]) <= height
                    if len(contribution_headers) == 1 else ROW_LABEL.fullmatch(clean(c['text'])))]
                # Actual aligned cells delimit the table. A heading elsewhere in
                # the document does not turn free-standing prose into a table row.
                rows = sorted([c for c in peers if c['box'][0] >= x - height
                               and c['box'][1] > bottom and any(
                                   c['box'][2] < label['box'][0] and same_row(c, label) for label in labels)],
                              key=lambda c: c['box'][1])
                last = bottom
                for row in rows:
                    if row['box'][1] - last > 3 * height or any(
                        last <= c['box'][1] < row['box'][1] and c['box'][0] <= x
                        and (PERSONAL_HEADING.fullmatch(clean(c['text'])) or NUMBERED.match(c['text'])
                             or clean(c['text']).startswith('팀 전체')) for c in peers):
                        break
                    last = row['box'][3]
                if labels and unit['box'][3] <= last and unit['box'][2] < min(c['box'][0] for c in labels):
                    return True
            return False
        if any(cells[0]['start'] < unit['end'] and cells[-1]['end'] > unit['start']
               for _, cells in self.text_table_rows()):
            return True
        # Recognize a bounded column-major OCR block without assigning its rows.
        # Stop at prose, a new heading, or a blank line, even if more tables follow.
        for i, header in enumerate(self.lines):
            if ('기술 스택' in header['text'] and '본인 기여 여부' in header['text']
                    and header['start'] == unit['start']):
                return bool(re.search(r'직접\s*(?:사용|구현|설계)|일부\s*설정|팀원\s*담당|미수행', header['text']))
            if not TECH_HEADER.fullmatch(clean(header['text'])) or i + 1 == len(self.lines):
                continue
            contribution = self.lines[i + 1]
            if not CONTRIBUTION_HEADER.fullmatch(clean(contribution['text'])):
                continue
            block, last = [], header['end']
            for entry in self.lines[i + 1:]:
                text = clean(entry['text'])
                if re.search(r'\n\s*\n', self.text[last:entry['start']]) or not (
                    CONTRIBUTION_HEADER.fullmatch(text) or ROW_LABEL.fullmatch(text)
                    or re.fullmatch(r'[A-Za-z][A-Za-z0-9 .+#/\-]*', text)):
                    break
                block.append(entry)
                last = entry['end']
            if unit in block and any(ROW_LABEL.fullmatch(clean(c['text'])) for c in block):
                return True
        return False

    def section(self, unit, positioned):
        units = (sorted([c for c in self.cells if c['space'] == unit['space']],
                        key=lambda c: (c['box'][1], c['box'][0])) if positioned else self.lines)
        heading = None
        description = None
        circled_list = False
        previous = None
        for entry in units:
            text = clean(entry['text'])
            if PERSONAL_HEADING.fullmatch(text):
                heading = entry
                description, circled_list = None, False
            elif heading:
                # Only the role description immediately under this heading may
                # contain a colon without ending the personal-work section.
                role_description = previous == heading and bool(ROLE_DESCRIPTION.match(text))
                number, heading_number = NUMBERED.match(entry['text']), NUMBERED.match(heading['text'])
                numbered_heading = bool(number and (circled_list or (
                    entry['box'][0] <= heading['box'][0] + 5 if positioned else
                    heading_number and int(number[1]) >= int(heading_number[1]))))
                boundary = not role_description and (
                    (not performed(text) and not NEGATIVE.search(text)) or numbered_heading or bool(
                        re.search(r'[:：]|^#{1,6}\s|^팀\s*전체', entry['text']))
                    or TECH_HEADER.fullmatch(text) or CONTRIBUTION_HEADER.fullmatch(text)
                    or self.in_table(entry, positioned))
                if positioned:
                    h = heading['box']
                    boundary |= (not h[0] - 5 <= entry['box'][0] <= h[0] + 3 * (h[3] - h[1])
                                 or entry['box'][1] < h[3]
                                 or (previous is not None and entry['box'][1] - previous['box'][3] > 3 * (h[3] - h[1])))
                elif previous and re.search(r'\n\s*\n', self.text[previous['end']:entry['start']]):
                    boundary = True
                if boundary:
                    heading = None
                elif role_description:
                    description = entry
                elif re.match(r'^\s*[①-⑳]', entry['text']):
                    circled_list = True
            if entry['start'] == unit['start'] and entry['end'] == unit['end']:
                if not heading or heading == entry:
                    return []
                return [self.span(heading, 'personal_section')] + (
                    [self.span(description, 'section_description')] if description and description != entry else [])
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
        if not has_geometry:
            cells = self.text_cells(unit)
            if cells:
                cells = [c for c in cells if c['start'] < end and c['end'] > start and names_skill(name, c['text'])]
                if len(cells) != 1:
                    return None
                unit = cells[0]
        a, b = max(start, unit['start']), min(end, unit['end'])
        # The original model quote/offsets remain untouched in verify_experiences.
        # Judgment reads the full source clause, never a clipped model substring.
        local = unit['text'].strip()
        judgment, actor = source_clause(name, unit['text'], a - unit['start'], b - unit['start'])
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
        ambiguous_table = not table and not context and self.in_table(unit, has_geometry)
        flattened_rows = ambiguous_table and not has_geometry and (
            '본인 기여 여부' in local or len(re.findall(
                r'직접\s*(?:사용|구현|설계)|일부\s*설정|팀원\s*담당|미수행', local)) > 1)
        if flattened_rows:
            activity = name + ' · 수행 내용 미확인'
        elif performed(judgment) or NEGATIVE.search(judgment) or TEAM.search(judgment):
            activity = clean(local)
        elif label:
            activity = clean(local) + ' · ' + label
        elif ambiguous_table:
            # A technology in an unresolved table is a mention, not performed work.
            activity = clean(local)
        else:
            return None
        actor_text = '' if flattened_rows else judgment + ' ' + label
        if (not flattened_rows and (negates_skill(name, judgment) or NEGATIVE.search(label))) or NON_WORK.search(actor_text):
            scope, reason = 'unknown', 'not_performed'
        elif not flattened_rows and (actor == 'team' or TEAM.search(label)):
            scope, reason = 'team', 'explicit_team'
        elif not flattened_rows and actor != 'unknown' and ((table and ROW_LABEL.fullmatch(label))
                                     or (context and not table) or actor == 'personal'):
            scope, reason = 'personal', 'document_personal'
        else:
            scope, reason = 'unknown', 'ambiguous_table_row' if ambiguous_table else 'actor_unspecified'
        # Repeated identical quotations have no unique model-supplied location.
        if self.locate(quote)[1]:
            scope, reason, context, method = 'unknown', 'ambiguous_source_location', [], 'quote'
        return {'activity': activity, 'contribution_scope': scope,
                'contribution_basis': {'source': 'document', 'method': method, 'reason': reason,
                                       'context': context}}

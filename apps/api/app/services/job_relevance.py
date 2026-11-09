"""Conservative, inspectable source rules. No provider calls or global skill blacklist.

Recognized occupational conflicts are checked against core duties, never a company's
technology list. Unrecognized occupations retain the existing title matcher.
"""
import re
import unicodedata

HEADINGS = (
    ('preferred', r'preferred(?: qualifications| requirements)?|nice[ -]to[ -]haves?|bonus(?: points)?|우대(?:사항| 요건)?'),
    ('required', r'requirements?|(?:minimum |required |basic )?qualifications|what you bring|필수(?: 요건)?|자격요건'),
    ('duty', r'responsibilities|(?:key |core )?duties|what you(?: will|\x27ll) (?:do|be doing)|the role|업무|주요 업무'),
    ('context', r'about (?:us|the company)|company(?: overview)?|our (?:customers|clients|partners)|benefits|회사 소개|복리후생'),
)
FAMILIES = {
    'data': r'data (?:analyst|analytics|analysis|scientist)|\bbi analyst\b|데이터\s*분석|데이터\s*사이언',
    'mechanical': r'mechanical(?: design)? engineer|cad designer|기계\s*설계',
    'security': r'(?:security|soc|cybersecurity) (?:data )?(?:analyst|engineer)|보안\s*(?:분석|관제|엔지니어)|침해\s*사고',
}
DUTIES = {
    'data': r'\banaly[sz]\w*\b[^.\n]*(?:data|metrics)|\b(?:build|create|develop|maintain)\w*\b[^.\n]*(?:dashboard|reports?)|데이터.*분석',
    'mechanical': r'\bdesign\w*\b[^.\n]*(?:mechanical|parts|assembl|tooling)|\b(?:create|design)\w*\b[^.\n]*3d models?|기계.*설계',
    'security': r'\b(?:investigat|respond|monitor)\w*\b[^.\n]*(?:security|threat|incidents?)|threat hunting|보안.*(?:관제|대응)',
}
MANUFACTURING = r'\bmanufactur\w*|\bfactory\b|\bproduction (?:data|quality|metrics)\b|제조|생산|불량'


def _matching_text(text):
    """Normalize typography for matching only; source offsets/quotes stay original."""
    return ' '.join(unicodedata.normalize('NFKC', text).translate(str.maketrans('’‘ʼ', "'''")).split())


def source_segments(text):
    """Yield exact source offsets with a local section; headings never enter quotes."""
    kind = 'unknown'
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = _matching_text(line).strip('#* ')
        for candidate, pattern in HEADINGS:
            match = re.match(r'^(?:' + pattern + r')\s*(?::\s*|$)', stripped, re.I)
            if match:
                kind = candidate
                break
        yield {'start': offset, 'end': offset + len(line), 'text': line.strip(), 'section': kind}
        offset += len(line)


def target_context(career_goal='', target_role='', keywords=()):
    primary = target_role or next((k['keyword'] for k in keywords if k['relation'] == 'direct'), '')
    text = primary + ' ' + (career_goal or '')
    # An explicit specialized occupation takes precedence over the word "data".
    family = next((f for f in ('security', 'mechanical', 'data') if re.search(FAMILIES[f], primary, re.I)), None)
    family = family or next((f for f in ('security', 'mechanical', 'data') if re.search(FAMILIES[f], text, re.I)), None)
    return {'family': family, 'manufacturing': bool(re.search(MANUFACTURING, text, re.I))}


def classify_job(job, target):
    title = job.get('title') or ''
    segments = list(source_segments(job.get('description_text') or ''))
    duties = '\n'.join(s['text'] for s in segments if s['section'] == 'duty')
    # Unsectioned prose can corroborate a role; company/requirements cannot.
    if not duties:
        duties = '\n'.join(s['text'] for s in segments if s['section'] == 'unknown')
    families = {f for f, pattern in DUTIES.items() if re.search(pattern, duties, re.I)}
    title_families = {f for f, pattern in FAMILIES.items() if re.search(pattern, title, re.I)}
    family = target['family']
    domain = bool(re.search(MANUFACTURING, title + '\n' + duties, re.I))
    reasons = []
    if family and families and family not in families:
        reasons.append('core_duties_mismatch')
    elif family and not families and title_families and family not in title_families:
        reasons.append('occupation_mismatch')
    if family == 'data' and target['manufacturing'] and not domain:
        reasons.append('target_domain_not_evidenced')
    relation = job['match_type']
    # A general analyst may inspect a specialized analysis job, with lower priority.
    if not reasons and family == 'data' and domain and not target['manufacturing'] and relation == 'direct':
        relation = 'related'
    return {'eligible': not reasons, 'reasons': reasons, 'match_type': relation,
            'target_family': family, 'core_families': sorted(families),
            'manufacturing_domain': domain, 'core_duties': duties,
            'reason': 'specialized_analysis_sample' if relation != job['match_type'] else 'title_and_duties_consistent' if family in families else 'title_match_duties_unclassified'}


def _evidence_clauses(text):
    """Separate independent requirements, preserving lists with a shared predicate."""
    predicate = r'\b(?:required|needed|necessary|mandatory|essential|preferred|require[sd]?|needs?)\b'
    # Sentence boundaries leave tool names such as React.js intact.
    for sentence in re.split(r'(?<=[.!?])\s+|;\s*', text):
        chunks = re.split(r'(,\s*(?:(?:and|but|whereas|while|however)\s+)?|\s+(?:and|but|whereas|while|however)\s+)', sentence, flags=re.I)
        clause = chunks[0]
        for index in range(1, len(chunks), 2):
            separator, following = chunks[index:index + 2]
            contrasting = re.search(r'\b(?:but|whereas|while|however)\b', separator, re.I)
            independent = (re.search(predicate, clause, re.I)
                           and re.search(predicate, ''.join(chunks[index + 1:]), re.I))
            if contrasting or independent:
                yield clause
                clause = following
            else:
                clause += separator + following
        yield clause


def _negates_skill(clause, matches_skill):
    """A negative requirement must name this skill in its subject/object scope."""
    clause = _matching_text(clause)
    requirement = r'(?:required|needed|necessary|mandatory|essential)\b'
    patterns = (
        r'\bno\s+(.+?)\s+(?:(?:is|are)\s+)?' + requirement,
        r'(.+?)\s+(?:(?:is|are)\s+)?not\s+' + requirement,
        r"(.+?)\s+(?:isn't|aren't)\s+" + requirement,
        r"\b(?:do not|does not|don't|doesn't)\s+(?:need|require)\s+(.+)",
    )
    return any(matches_skill(match[1]) for pattern in patterns
               for match in re.finditer(pattern, clause, re.I))


def evidence_context(text, start, end, matches_skill):
    """Inspect skill-bearing clauses, so a quote cannot borrow another line's heading."""
    parts = []
    for segment in source_segments(text):
        if segment['start'] >= end or segment['end'] <= start:
            continue
        # Inspect the overlapping source clause, not just the quoted substring:
        # a short quote such as "CAD experience" must not drop its preceding "No".
        local = text[segment['start']:segment['end']]
        cursor = 0
        for clause in _evidence_clauses(local):
            clause_start = local.index(clause, cursor)
            cursor = clause_start + len(clause)
            if not clause.strip():
                continue
            if segment['start'] + clause_start >= end or segment['start'] + cursor <= start:
                continue
            if matches_skill(clause):
                section = segment['section']
                if re.search(r'\b(?:our (?:customers|clients|partners)|other teams?|the (?:design|security) team)\b', clause, re.I):
                    section = 'context'
                negated = _negates_skill(clause, matches_skill)
                parts.append((section, clause, negated))
    if not parts:
        return 'unknown', '', False
    actionable = [p for p in parts if p[0] != 'context' and not p[2]]
    chosen = actionable or parts
    sections = {p[0] for p in chosen}
    section = next((k for k in ('required', 'preferred', 'duty', 'unknown', 'context') if k in sections), 'unknown')
    return section, '\n'.join(p[1] for p in chosen), bool(actionable)

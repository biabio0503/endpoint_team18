"""Collect public Dacon listings and active competition detail pages."""
from __future__ import annotations
import re
import sys
import time
from datetime import date
from urllib.parse import urlsplit
from crawling.dacon.validation import extract_evidence

SOURCES = ('https://dacon.io/', 'https://dacon.io/competitions')
PATH = re.compile(r'^/(?:competitions/(?:official|open)|competition)/(\d+)(?:/|$)')


def status_of(raw):
    raw = ' '.join((raw or '').split())
    explicit = re.sub(r'(?:종료|마감)까지\s*D\s*[-−]?\s*(?:\d+|day)', '', raw, flags=re.I)
    if re.search(r'마감|연습|종료', explicit):
        return '연습' if '연습' in explicit else '마감' if '마감' in explicit else '종료'
    if re.search(r'(?:접수|모집|진행)\s*예정', raw):
        return '접수예정'
    if re.search(r'모집\s*중', raw):
        return '모집중'
    if re.search(r'진행\s*중|D\s*[-−]\s*\d+|D\s*[-−]?\s*day|D\s*[-−]\s*0', raw, re.I):
        return '진행중'
    return 'unknown'


def normalize(card, source):
    parsed = urlsplit(card.get('href', ''))
    match = PATH.match(parsed.path)
    if parsed.scheme != 'https' or parsed.hostname not in ('dacon.io', 'www.dacon.io') or not match:
        return None
    title = ' '.join((card.get('title') or '').split())
    if not title:
        return None
    key = match.group(1)
    return {'id': key, 'url': f'https://dacon.io{parsed.path}', 'title': title,
            'status': status_of(card.get('status')), 'prize': ' '.join((card.get('prize') or '').split()) or None,
            'start_date': None,
            'listing_date': (card.get('displayed_date') or '').strip().replace('.', '-') or None,
            'end_date': None,
            'sources': [source]}


def merge_cards(cards):
    result = {}
    for card, source in cards:
        item = normalize(card, source)
        if not item:
            continue
        old = result.get(item['id'])
        if old is None:
            result[item['id']] = item
            continue
        # An explicit closed listing always wins; never retain an active cache entry.
        previous, current = old['status'], item['status']
        ended = {'종료', '마감', '연습'}
        if current in ended or previous in ended:
            old['status'] = current if current in ended else previous
        elif previous == 'unknown':
            old['status'] = current
        old['sources'] = sorted(set(old['sources'] + item['sources']))
        for key in ('prize', 'start_date', 'end_date', 'listing_date'):
            if not old[key] and item[key]:
                old[key] = item[key]
    return sorted(result.values(), key=lambda x: x['id'])


CARD_JS = r'''() => Array.from(document.querySelectorAll('a[href]')).map(a => {
 const href = a.href;
 const m = new URL(href).pathname.match(/^\/(?:competitions\/(?:official|open)|competition)\/\d+(?:\/|$)/);
 if (!m) return null;
 const dday = a.querySelector('.dday');
 const progress = a.querySelector('progress');
 const dateRow = progress && progress.nextElementSibling;
 const spans = dateRow ? Array.from(dateRow.querySelectorAll('span')) : [];
 const title = a.querySelector('.name')?.textContent || a.querySelector('img[alt]')?.getAttribute('alt')?.replace(/\s+(Image|이미지)$/, '');
 const prize = a.querySelector('.price')?.textContent || Array.from(a.querySelectorAll('span')).map(x => x.textContent.trim()).find(x => /^상금\s/.test(x));
 return {href, title, status: dday?.innerText || (spans.length > 1 ? spans[spans.length-1].innerText : ''),
         displayed_date: spans.length > 1 ? spans[0].innerText : '', prize: prize || ''};
}).filter(Boolean)'''


DATE_RANGE = re.compile(r'(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?\s*(?:\d{1,2}:\d{2})?\s*[~～–—]\s*(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})', re.I)


def parse_period(text):
    match = DATE_RANGE.search(text or '')
    if not match:
        return None, None
    try:
        values = [int(x) for x in match.groups()]
        start, end = date(*values[:3]), date(*values[3:])
        if end < start:
            return None, None
        return start.isoformat(), end.isoformat()
    except ValueError:
        return None, None


def progress(message):
    print('[진행] ' + message, file=sys.stderr, flush=True)


DAKER_CARD_JS = r'''() => Array.from(document.querySelectorAll('a[href]')).map(a => {
 const u = new URL(a.href);
 if (u.hostname !== 'daker.ai' || !/^\/public\/hackathons\/[^/]+\/?$/.test(u.pathname)) return null;
 const progress = a.querySelector('progress');
 const row = progress && progress.nextElementSibling;
 const spans = row ? Array.from(row.querySelectorAll('span')) : [];
 const img = a.querySelector('img[alt]');
 if (!img) return null;
 return {href: u.origin + u.pathname, title: img.alt.replace(/\s+(Image|이미지)$/, ''),
         status: spans.length ? spans[spans.length-1].innerText.trim() : a.innerText};
}).filter(Boolean)'''

DAKER_DETAIL_JS = r'''() => {
 const root = document.querySelector('main main');
 if (!root) return null;
 const title = root.querySelector('h1');
 if (!title) return null;
 const paragraphs = Array.from(root.querySelectorAll('p'));
 const prizeLabel = paragraphs.find(p => p.textContent.trim() === '상금');
 const prize = prizeLabel?.nextElementSibling?.textContent?.trim() || null;
 const all = Array.from(root.querySelectorAll('div, span, p')).filter(e => !e.children.length).map(e => e.innerText || '');
 const period = all.find(t => /20\d{2}\.\d{1,2}\.\d{1,2}\s*~\s*20\d{2}\.\d{1,2}\.\d{1,2}/.test(t)) || '';
 const before = root.innerText.split(title.innerText)[0].trim();
 const description = title.parentElement?.querySelector('p')?.textContent?.trim() || null;
 const overview = root.querySelector('#section-overview div[data-state][id]')?.innerText?.trim() || null;
 const hostLabel = paragraphs.find(p => p.textContent.trim() === '주최');
 return {title: title.innerText.trim(), prize, period, status: before, description, overview,
         host: hostLabel?.nextElementSibling?.textContent?.trim() || null, body: root.innerText};
}'''


def daker_candidates(cards):
    found = {}
    for card in cards:
        url = urlsplit(card.get('href', ''))
        if url.scheme != 'https' or url.hostname != 'daker.ai' or not re.fullmatch(r'/public/hackathons/[a-zA-Z0-9_-]+/?', url.path):
            continue
        slug = url.path.rstrip('/').split('/')[-1]
        if slug in found and found[slug]['status'] in ('종료', '마감', '연습'):
            continue
        found[slug] = {'id': 'daker:' + slug, 'url': 'https://daker.ai' + url.path.rstrip('/'),
                       'title': card.get('title', ''), 'status': status_of(card.get('status'))}
    return list(found.values())


# Verified on the public /competitions page: button.bgBtn loads another 15
# cards. The other "더보기" belongs to a footer/modal, not the competition list.
class ListingFailure(Exception):
    def __init__(self, cards):
        self.cards = cards
        super().__init__('listing_incomplete')


def listing_cards(page):
    seen, result = set(), []
    while True:
        cards = page.evaluate(CARD_JS)
        identities = {m.group(1) for c in cards if (m := PATH.match(urlsplit(c['href']).path))}
        if not identities - seen:
            break
        result.extend(cards)
        seen.update(identities)
        more = page.locator('button.bgBtn').filter(has_text='더보기')
        if not more.count() or not more.first.is_visible() or not more.first.is_enabled():
            break
        before = sorted(identities)
        try:
            # Observed public UI endpoint. Click the real button; no guessed page
            # numbers or private endpoints. Wait for its own response, not ads.
            with page.expect_response(lambda r: urlsplit(r.url).hostname == 'app.dacon.io'
                                      and urlsplit(r.url).path == '/api/v1/competition/list', timeout=15000) as pending:
                more.first.click()
            response = pending.value
            if response.status >= 400:
                raise ConnectionError('listing_unavailable')
            response.body()  # Await the completed response before inspecting cards.
        except Exception:
            raise ListingFailure(result) from None
        try:
            page.wait_for_function(r"""(before) => {
              const ids = [...new Set(Array.from(document.querySelectorAll('a[href]')).map(a =>
                new URL(a.href).pathname.match(/^\/(?:competitions\/(?:official|open)|competition)\/(\d+)/)?.[1]).filter(Boolean))].sort();
              return JSON.stringify(ids) !== JSON.stringify(before);
            }""", arg=before, timeout=5000)
        except Exception:
            # A successful completed response with no additional cards is the
            # end (including a server that repeats the previous page).
            if {m.group(1) for c in page.evaluate(CARD_JS) if (m := PATH.match(urlsplit(c['href']).path))} <= seen:
                break
            raise ListingFailure(result) from None
    return result


APPLICATION_LINK_JS = r"""() => Array.from(document.querySelectorAll('main a[href], .ql-editor a[href]'))
 .filter(a => /^(?:온라인\s*)?(?:참가\s*)?(?:신청|접수)(?:하기)?$/.test(a.textContent.trim()))
 .map(a => a.href)"""


def application_link(page):
    from services.activity_identity import official_url
    links = set(filter(None, (official_url(u) for u in page.evaluate(APPLICATION_LINK_JS))))
    return {'official_application_url': links.pop()} if len(links) == 1 else {}


def read_dacon(page, item):
    response = page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
    if not response or response.status >= 400 or not PATH.match(urlsplit(page.url).path) or urlsplit(page.url).hostname not in ('dacon.io', 'www.dacon.io'):
        raise ConnectionError(f"상세 페이지를 읽지 못했습니다: {item['id']}")
    body = page.locator('body').inner_text()
    closure = extract_evidence(body)
    if closure['application_closed'] or closure['application_cancelled']:
        return {**item, **closure}
    # The public header shows a single competition date range in a li.
    page.wait_for_function("() => Array.from(document.querySelectorAll('li')).some(e => /20\\d{2}[.\\-/]\\d{1,2}[.\\-/]\\d{1,2}.*[~～–—].*20\\d{2}/.test(e.innerText))", timeout=25000)
    header_dates = page.locator('li:has(.mdi-clock-outline)')
    lines = header_dates.all_inner_texts() if header_dates.count() else page.locator('li').all_inner_texts()
    ranges = [parse_period(line) for line in lines]
    ranges = [pair for pair in ranges if pair[0]]
    if len(set(ranges)) != 1:
        raise RuntimeError(f"대회 기간을 확정하지 못했습니다: {item['id']}")
    item['start_date'], item['end_date'] = ranges[0]
    page.wait_for_function('''() => Array.from(document.querySelectorAll(
        '.ql-editor, #section-overview [data-state][id], .markdown-body, .competition-description, .overview-description'
        )).some(e => e.innerText.trim().length > 0)''', timeout=25000)
    overview = page.evaluate(r'''() => {
        const el = document.querySelector('.ql-editor, #section-overview [data-state][id], .markdown-body, .competition-description, .overview-description');
        return el?.innerText?.trim() || null;
    }''')
    body = page.locator('body').inner_text()
    description = page.locator('meta[name="description"]').get_attribute('content') if page.locator('meta[name="description"]').count() else None
    item['description'] = (overview or description or '').strip()[:2000] or None
    item['overview'] = overview
    # Follow only public overview links on the same competition to
    # find registration rules; no student request reaches this code.
    links = page.locator('a[href]').evaluate_all('(links) => links.map(a => a.href)')
    related = sorted({u for u in links if urlsplit(u).hostname == 'dacon.io'
        and re.fullmatch(rf'/competitions/(?:official|open)/{item["id"]}/overview/(?:rules|schedule)', urlsplit(u).path)
        and u.rstrip('/') != item['url'].rstrip('/')})
    for url in related:
        time.sleep(3)
        response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
        if not response or response.status >= 400:
            raise ConnectionError('detail_unavailable')
        page.wait_for_selector('li:has(.mdi-clock-outline)', timeout=25000)
        page.wait_for_function("() => Array.from(document.querySelectorAll('.ql-editor')).some(e => e.innerText.trim())", timeout=25000)
        body += '\n' + page.locator('body').inner_text()
    item.update(extract_evidence(body, (item['start_date'], item['end_date'])))
    item.update(application_link(page))
    item.pop('listing_date', None)
    return item


def read_daker(page, item):
    response = page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
    target = urlsplit(page.url)
    if not response or response.status >= 400 or target.hostname != 'daker.ai' or target.path.rstrip('/') != urlsplit(item['url']).path.rstrip('/'):
        raise ConnectionError(f"상세 페이지를 읽지 못했습니다: {item['id']}")
    page.wait_for_selector('main main h1', timeout=25000)
    closure = extract_evidence(page.locator('main main').inner_text())
    if closure['application_closed'] or closure['application_cancelled']:
        return {**item, **closure}
    page.wait_for_function("() => Array.from(document.querySelectorAll('main main div, main main span, main main p')).some(e => !e.children.length && /20\\d{2}\\.\\d{1,2}\\.\\d{1,2}\\s*~\\s*20\\d{2}/.test(e.innerText || ''))", timeout=25000)
    detail = page.evaluate(DAKER_DETAIL_JS)
    state = status_of(detail['status']) if detail else 'unknown'
    if state not in ('진행중', '모집중', '접수예정'):
        # If detail says closed, do not add the candidate.
        if state in ('종료', '마감', '연습'):
            return {**item, 'status': state}
        else:
            raise RuntimeError('데이커 상세 상태를 확인하지 못했습니다.')
    start, end = parse_period(detail['period'])
    if not start:
        raise RuntimeError(f"대회 기간을 확정하지 못했습니다: {item['id']}")
    return {**item, 'title': detail['title'], 'prize': detail['prize'],
                   'status': state, 'start_date': start, 'end_date': end,
                   'description': detail.get('description'), 'overview': detail.get('overview'),
                   'host': detail.get('host'),
                   **extract_evidence(detail.get('body'), (start, end)),
                   **application_link(page)}


def crawl_details(page, records):
    result = []
    for raw in records:
        item = {k: v for k, v in raw.items() if k not in ('verification_error', 'official_application_url')}
        if item['status'] in ('종료', '마감', '연습'):
            result.append(item)
            continue
        time.sleep(0.3)
        try:
            if item.get('source') == 'daker' or item['id'].startswith('daker:'):
                checked = read_daker(page, item)
            else:
                item['id'] = item['id'].removeprefix('dacon:')
                checked = read_dacon(page, item)
            result.append(checked)
        except Exception as error:
            # Isolate detail failures; retain successful work on other records.
            code = 'network_error' if isinstance(error, (OSError, ConnectionError)) or 'net::' in str(error) else 'parse_error'
            result.append({**item, 'verification_error': code})
    return result


def _crawl(existing=None):
    from playwright.sync_api import sync_playwright
    from crawling.activities.batch import Batch
    cards, daker_cards, failures = [], [], 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(service_workers='block', timezone_id='Asia/Seoul', locale='ko-KR')
        page = context.new_page()
        page.set_default_timeout(25000)
        try:
            if existing is None:
                for index, source in enumerate(SOURCES):
                    try:
                        response = page.goto(source, wait_until='domcontentloaded', timeout=30000)
                        if not response or response.status >= 400:
                            raise ConnectionError('listing_unavailable')
                        page.wait_for_function("""() => document.querySelector('a[href*=\"/competitions/official/\"], a[href*=\"/competitions/open/\"], a[href*=\"/competition/\"]') ||
                            /등록된 대회가 없습니다|진행 중인 대회가 없습니다/.test(document.body?.innerText || '')""", timeout=25000)
                        if index == 0:
                            daker_cards = page.evaluate(DAKER_CARD_JS)
                        page_cards = page.evaluate(CARD_JS) if index == 0 else listing_cards(page)
                        if not page_cards and not re.search(r'등록된 대회가 없습니다|진행 중인 대회가 없습니다', page.locator('body').inner_text()):
                            raise ValueError('listing_structure_changed')
                        cards.extend((card, source) for card in page_cards)
                    except ListingFailure as error:
                        cards.extend((card, source) for card in error.cards)
                        failures += 1
                    except Exception:
                        failures += 1
                existing = [*merge_cards(cards), *daker_candidates(daker_cards)]
            result = crawl_details(page, existing)
            parse = sum(i.get('verification_error') == 'parse_error' for i in result)
            network = sum(i.get('verification_error') == 'network_error' for i in result)
            status = 'error' if failures == len(SOURCES) else 'partial' if failures or parse or network else 'success'
            return Batch(result, status, {'fetched_items': len(existing), 'failed_listings': failures,
                                         'parse_failures': parse, 'network_failures': network})
        finally:
            browser.close()


def collect():
    return _crawl()


def recheck(records):
    try:
        return _crawl(records).items
    except Exception:
        return [{**item, 'verification_error': 'network_error'} for item in records]

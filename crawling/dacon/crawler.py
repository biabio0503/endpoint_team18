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


def collect():
    progress('Playwright 불러오는 중')
    from playwright.sync_api import sync_playwright
    cards = []
    daker_cards = []
    progress('Playwright 실행 준비 중')
    with sync_playwright() as p:
        progress('Chromium 실행 중')
        browser = p.chromium.launch(headless=True)
        # Daker formats schedule times in the browser's local timezone. Render
        # hosts run in UTC; parsing those strings as KST would shift deadlines.
        context = browser.new_context(service_workers='block', timezone_id='Asia/Seoul', locale='ko-KR')
        page = context.new_page()
        # Only listing pages and detail URLs explicitly found in those listings.
        page.set_default_timeout(25000)
        try:
            for index, source in enumerate(SOURCES):
                if index:
                    time.sleep(3)
                progress(f'공개 목록 접속 중: {source}')
                response = page.goto(source, wait_until='domcontentloaded', timeout=30000)
                if not response or response.status >= 400:
                    raise RuntimeError('공개 목록 페이지를 열지 못했습니다.')
                page.wait_for_function('''() => document.querySelector('a[href*="/competitions/official/"], a[href*="/competitions/open/"], a[href*="/competition/"]') ||
                    /등록된 대회가 없습니다|진행 중인 대회가 없습니다/.test(document.body?.innerText || '')''', timeout=25000)
                if index == 0:
                    daker_cards = page.evaluate(DAKER_CARD_JS)
                # Only inspect cards already loaded; do not repeatedly request old pages.
                page_cards = page.evaluate(CARD_JS)
                if not page_cards and not re.search(r'등록된 대회가 없습니다|진행 중인 대회가 없습니다', page.locator('body').inner_text()):
                    raise RuntimeError('대회 카드가 없거나 페이지 구조가 변경되었습니다.')
                cards.extend((card, source) for card in page_cards)
            result = merge_cards(cards)
            if result and not any(x['status'] in ('진행중', '모집중', '종료', '마감', '연습') for x in result):
                raise RuntimeError('대회 상태를 판별하지 못해 캐시를 변경하지 않았습니다.')
            for item in result:
                if item['status'] not in ('진행중', '모집중'):
                    continue
                time.sleep(3)
                progress(f"대회 상세 확인 중: {item['id']}")
                response = page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
                if not response or response.status >= 400 or not PATH.match(urlsplit(page.url).path) or urlsplit(page.url).hostname not in ('dacon.io', 'www.dacon.io'):
                    raise RuntimeError(f"상세 페이지를 읽지 못했습니다: {item['id']}")
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
                    and re.fullmatch(rf'/competitions/(?:official|open)/{item["id"]}/overview/(?:rules|schedule)', urlsplit(u).path)})
                for url in related:
                    time.sleep(3)
                    response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    if not response or response.status >= 400:
                        raise RuntimeError('상세 신청 조건을 읽지 못했습니다.')
                    page.wait_for_selector('li:has(.mdi-clock-outline)', timeout=25000)
                    page.wait_for_function("() => Array.from(document.querySelectorAll('.ql-editor')).some(e => e.innerText.trim())", timeout=25000)
                    body += '\n' + page.locator('body').inner_text()
                item.update(extract_evidence(body, (item['start_date'], item['end_date'])))
                item.pop('listing_date', None)
            for item in daker_candidates(daker_cards):
                if item['status'] in ('종료', '마감', '연습'):
                    result.append(item)
                    continue
                time.sleep(3)
                progress(f"데이커 대회 상세 확인 중: {item['id']}")
                response = page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
                target = urlsplit(page.url)
                if not response or response.status >= 400 or target.hostname != 'daker.ai' or target.path.rstrip('/') != urlsplit(item['url']).path.rstrip('/'):
                    raise RuntimeError(f"상세 페이지를 읽지 못했습니다: {item['id']}")
                page.wait_for_selector('main main h1', timeout=25000)
                page.wait_for_function("() => Array.from(document.querySelectorAll('main main div, main main span, main main p')).some(e => !e.children.length && /20\\d{2}\\.\\d{1,2}\\.\\d{1,2}\\s*~\\s*20\\d{2}/.test(e.innerText || ''))", timeout=25000)
                detail = page.evaluate(DAKER_DETAIL_JS)
                state = status_of(detail['status']) if detail else 'unknown'
                if state not in ('진행중', '모집중'):
                    # If detail says closed, do not add the candidate.
                    if state in ('종료', '마감', '연습'):
                        result.append({**item, 'status': state})
                    else:
                        raise RuntimeError('데이커 상세 상태를 확인하지 못했습니다.')
                    continue
                start, end = parse_period(detail['period'])
                if not start:
                    raise RuntimeError(f"대회 기간을 확정하지 못했습니다: {item['id']}")
                result.append({**item, 'title': detail['title'], 'prize': detail['prize'],
                               'status': state, 'start_date': start, 'end_date': end,
                               'description': detail.get('description'), 'overview': detail.get('overview'),
                               'host': detail.get('host'),
                               **extract_evidence(detail.get('body'), (start, end))})
        finally:
            failed = sys.exc_info()[0] is not None
            try:
                browser.close()
            except Exception:
                if not failed:
                    raise
    return result

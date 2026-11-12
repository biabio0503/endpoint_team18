"""Collect public Dacon listings and active competition detail pages."""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

KST = timezone(timedelta(hours=9))
LAST_DAY = date(2026, 11, 15)
DEFAULT_CACHE = Path(__file__).with_name('competitions.json')
SOURCES = ('https://dacon.io/', 'https://dacon.io/competitions')
PATH = re.compile(r'^/(?:competitions/(?:official|open)|competition)/(\d+)(?:/|$)')


def status_of(raw):
    raw = ' '.join((raw or '').split())
    if re.search(r'마감|연습', raw) or (re.search(r'종료', raw) and not re.search(r'종료까지\s*D', raw, re.I)):
        return '연습' if '연습' in raw else '마감' if '마감' in raw else '종료'
    if re.search(r'모집\s*중', raw):
        return '모집중'
    if re.search(r'진행\s*중|D\s*[-−]\s*\d+|D\s*[-−]?\s*day|D\s*[-−]\s*0', raw, re.I):
        return '진행중'
    return 'unknown'


def end_date_from_status(raw, today=None):
    raw = ' '.join((raw or '').split())
    match = re.search(r'D\s*[-−]\s*(\d+)|D\s*[-−]?\s*day', raw, re.I)
    if not match:
        return None
    days = int(match.group(1) or 0)
    return ((today or datetime.now(KST).date()) + timedelta(days=days)).isoformat()


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
            'end_date': end_date_from_status(card.get('status')),
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
        # Conflicting statuses cannot safely justify deletion or insertion.
        previous, current = old['status'], item['status']
        active = {'진행중', '모집중'}
        ended = {'종료', '마감', '연습'}
        if previous == 'conflict':
            pass
        elif previous != 'unknown' and current != 'unknown' and ((previous in active) != (current in active)):
            old['status'] = 'conflict'
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
 if (!progress || spans.length < 2 || !img) return null;
 return {href: u.origin + u.pathname, title: img.alt.replace(/\s+(Image|이미지)$/, ''),
         status: spans[spans.length-1].innerText.trim()};
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
 return {title: title.innerText.trim(), prize, period, status: before, description, overview};
}'''


def daker_candidates(cards):
    found = {}
    for card in cards:
        url = urlsplit(card.get('href', ''))
        if url.scheme != 'https' or url.hostname != 'daker.ai' or not re.fullmatch(r'/public/hackathons/[a-zA-Z0-9_-]+/?', url.path):
            continue
        if status_of(card.get('status')) != '진행중':
            continue
        slug = url.path.rstrip('/').split('/')[-1]
        found[slug] = {'id': 'daker:' + slug, 'url': 'https://daker.ai' + url.path.rstrip('/'),
                       'title': card.get('title', ''), 'status': '진행중'}
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
        context = browser.new_context(service_workers='block')
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
                page.wait_for_selector('a[href*="/competitions/official/"], a[href*="/competition/"]', timeout=25000)
                if index == 0:
                    daker_cards = page.evaluate(DAKER_CARD_JS)
                # Only inspect cards already loaded; do not repeatedly request old pages.
                page_cards = page.evaluate(CARD_JS)
                if not page_cards:
                    raise RuntimeError('대회 카드가 없거나 페이지 구조가 변경되었습니다.')
                cards.extend((card, source) for card in page_cards)
            result = merge_cards(cards)
            if not result or not any(x['status'] in ('진행중', '모집중', '종료', '마감', '연습') for x in result):
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
                overview = page.evaluate(r'''() => {
                    const el = document.querySelector('#section-overview [data-state][id], .markdown-body, .competition-description, .overview-description');
                    return el?.innerText?.trim() || null;
                }''')
                item['description'] = None
                item['overview'] = overview
                item.pop('listing_date', None)
            for item in daker_candidates(daker_cards):
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
                    continue
                start, end = parse_period(detail['period'])
                if not start:
                    raise RuntimeError(f"대회 기간을 확정하지 못했습니다: {item['id']}")
                result.append({**item, 'title': detail['title'], 'prize': detail['prize'],
                               'status': state, 'start_date': start, 'end_date': end,
                               'description': detail.get('description'), 'overview': detail.get('overview')})
        finally:
            failed = sys.exc_info()[0] is not None
            try:
                browser.close()
            except Exception:
                if not failed:
                    raise
    return result


def run_once(path=DEFAULT_CACHE):
    path = Path(path)
    if path.exists():
        old_data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(old_data, dict) or not isinstance(old_data.get('competitions'), list):
            raise ValueError('잘못된 캐시 형식입니다.')
        old = {item['id']: item for item in old_data['competitions']}
    else:
        old = {}
    records = collect()
    current = dict(old)
    added, changed, removed = [], [], []
    for item in records:
        key, status = item['id'], item['status']
        if status in ('마감', '종료', '연습'):
            if key in current:
                del current[key]
                removed.append(key)
        elif status in ('진행중', '모집중'):
            record = {k: item.get(k) for k in ('id', 'title', 'prize', 'start_date', 'end_date', 'url', 'status', 'description', 'overview')}
            if key in current:
                for field in ('description', 'overview'):
                    if not record[field] and current[key].get(field):
                        record[field] = current[key][field]
            if key not in current:
                current[key] = record
                added.append(key)
            elif current[key] != record:
                current[key] = record
                changed.append(key)
    competitions = sorted(current.values(), key=lambda x: x['id'])
    if added or changed or removed or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as temp:
                temp_name = temp.name
                json.dump({'competitions': competitions}, temp, ensure_ascii=False, indent=2)
                temp.write('\n')
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    return {'added': added, 'changed': changed, 'removed': removed, 'competitions': competitions}


def main():
    parser = argparse.ArgumentParser(description='Collect Dacon public competitions to JSON')
    parser.add_argument('--scheduled', action='store_true', help='only run through 2026-11-15 KST')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    if args.scheduled and datetime.now(KST).date() > LAST_DAY:
        print(json.dumps({'status': 'schedule_ended'}))
        return 0
    try:
        result = run_once(args.cache)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc) or repr(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())

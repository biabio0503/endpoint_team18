"""Allowlisted offline fixture loader; intentionally has no network transport."""
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from config import ROOT
from . import html_fixture,pdf_text
from .models import Batch

FIXTURE_ROOT=ROOT.parents[1]/'data'/'reference'/'external-fixtures'
SOURCES={
 'fixture-jobs':{'folder':'jobs','adapter':'fixture_html','sets':('v1','v2','empty','partial','failure'),'kinds':('job_posting',)},
 'fixture-activities':{'folder':'activities','adapter':'fixture_html','sets':('v1',),'kinds':('competition','extracurricular')},
 'fixture-pdf':{'folder':'pdf','adapter':'fixture_pdf','sets':('v1',),'kinds':('competition',)},
}
MAX_FILE_BYTES=2*1024*1024

def collect(source_id,scope):
    config=SOURCES.get(source_id)
    if not config or scope.get('fixture_set') not in config['sets']:raise ValueError('unsupported_fixture_scope')
    directory=FIXTURE_ROOT/config['folder']/scope['fixture_set']
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    items=manifest['items']
    if not isinstance(items,list) or len(items)>100 or type(manifest.get('complete')) is not bool:raise ValueError('invalid_manifest')
    keys=[item.get('id') for item in items if isinstance(item,dict) and isinstance(item.get('id'),str)]
    if len(keys)!=len(set(keys)): raise ValueError('duplicate_item_key')
    evidence=[];failures=[];seen=set()
    for item in items:
        key=item.get('id') if isinstance(item,dict) else None
        try:
            if not isinstance(key,str) or not key or len(key)>200 or key in seen:raise ValueError('invalid_item_key')
            seen.add(key)
            url=urlsplit(item['url'])
            if url.scheme!='https' or url.netloc!='fixtures.invalid' or url.username or url.password:raise ValueError('invalid_fixture_url')
            if item['kind'] not in config['kinds']:raise ValueError('invalid_kind')
            name=item['file']
            if not isinstance(name,str) or Path(name).name!=name or name in ('.','..'):raise ValueError('invalid_file_path')
            path=directory/name
            if path.is_symlink() or not path.is_file():raise ValueError('fixture_unavailable')
            if path.stat().st_size>MAX_FILE_BYTES:raise ValueError('fixture_too_large')
            raw=path.read_bytes()
            parsed=(html_fixture if config['adapter']=='fixture_html' else pdf_text).parse(item,raw)
            evidence.append(replace(parsed, observed_at=datetime.now(timezone.utc).isoformat(timespec='microseconds')))
        except Exception:
            failures.append({'source_item_key':key if isinstance(key,str) else None,'error_code':'fixture_read_or_parse_failed'})
    coverage='partial' if failures or not manifest['complete'] else 'complete'
    return Batch(evidence,failures,len(items),coverage)

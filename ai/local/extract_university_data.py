import csv
import html
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'ai/local/data/university_source.html'
raw = source.read_text(encoding='utf-8')
pos = raw.index('횃불트리니티신학대학원대학교')
table = raw[raw.rfind('<table', 0, pos):raw.index('</table>', pos)]
rows = []
for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S | re.I):
    cells = [html.unescape(re.sub(r'<[^>]*>', '', c)).strip() for c in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)]
    if len(cells) >= 12:
        rows.append((cells[5], cells[11]))
out = root / 'ai/local/data/university_departments.csv'
with out.open('w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['학교명', '학과명'])
    writer.writerows(rows)
print('records:', len(rows), 'unique schools:', len({r[0] for r in rows}), 'unique departments:', len({r[1] for r in rows}))

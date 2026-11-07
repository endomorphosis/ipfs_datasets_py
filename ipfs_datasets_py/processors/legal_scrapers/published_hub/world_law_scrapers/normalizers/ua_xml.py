import re, html
ITEM = re.compile(r'<item name="([^"]+)">(.*?)</item>', re.S)
def docs(path):
    buf = []; inside = False; bad = 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('<document>'): buf = []; inside = True; continue
            if line.startswith('</document>'):
                inside = False; d = {}
                for k, v in ITEM.findall(''.join(buf)):
                    if k == 'TEXT_ED': d[k] = html.unescape(re.sub(r'<[^>]+>', '', v))
                    else: d[k] = ' | '.join(' '.join(html.unescape(t).split()) for t in re.findall(r'<text>(.*?)</text>', v, re.S))
                yield d; continue
            if inside: buf.append(line)

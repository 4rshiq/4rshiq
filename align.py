"""
Re-pads every row of the info column so the right edge lines up again.

How to use:
  1. Edit the text inside light_mode.svg and dark_mode.svg in any text editor,
     e.g. change  <tspan class="value">CSE</tspan>  to  <tspan class="value">B.Tech CSE</tspan>
     (do the same edit in BOTH files). Don't worry about the dots.
  2. Run:   python align.py
  3. Commit the changed SVGs.

Rows that are too long for the column are reported instead of changed - shorten the text
or raise WIDTH below.

WIDTH is the ONE place to change the column width. today.py reads it too, and this script
resizes the image to match. After changing WIDTH just run  python align.py  and commit.
"""
from lxml import etree

FILES = ['light_mode.svg', 'dark_mode.svg']
WIDTH = 60  # characters per row in the info column (change me, then run align.py)
CHAR_PX = 9.6        # width of one character in the SVG (16px font)
RIGHT_MARGIN = 30    # empty space to the right of the column, in pixels

SVG = '{http://www.w3.org/2000/svg}'


def split_rows(text_el):
    rows = []
    for tspan in text_el.findall(SVG + 'tspan'):
        if tspan.get('x') is not None:
            rows.append([tspan])
        elif rows:
            rows[-1].append(tspan)
    return rows


def text_len(el, count_text=True):
    n = len(el.text or '') if count_text else 0
    return n + len((el.tail or '').replace('\n', ''))


def align_file(path):
    tree = etree.parse(path)
    problems = []
    for text_el in tree.getroot().iter(SVG + 'text'):
        if not any(t.get('class') == 'cc' for t in text_el.iter(SVG + 'tspan')):
            continue  # this is the ASCII-art block
        for row in split_rows(text_el):
            if len(row) < 2:
                continue
            id_fillers = [t for t in row if (t.get('id') or '').endswith('_dots')]
            fillers = id_fillers or [t for t in row[1:] if t.get('class') == 'cc']
            if not fillers:
                continue
            filler = fillers[0] if (id_fillers or row[0].get('class') == 'cc') else fillers[-1]
            others = sum(text_len(t, t is not filler) for t in row)
            gap = WIDTH - others
            keys = [t.text or '' for t in row if t.get('class') == 'key']
            label = '.'.join(keys) if keys else (row[0].text or '').strip()
            if row[0].get('class') == 'cc':      # "key: ..... value" row
                if gap < 1:
                    problems.append((label, 1 - gap))
                    continue
                filler.text = {1: ' ', 2: '. '}.get(gap, ' ' + '.' * (gap - 2) + ' ')
            else:                                 # "- Section ------" header row
                if gap < 0:
                    problems.append((label, -gap))
                    continue
                filler.text = '-' * gap
    # resize the image so the wider/narrower column fits exactly
    root = tree.getroot()
    info_x = min(float(t.get('x')) for te in root.iter(SVG + 'text')
                 if any(t.get('class') == 'cc' for t in te.iter(SVG + 'tspan'))
                 for t in te.findall(SVG + 'tspan') if t.get('x'))
    pixel_width = f'{int(info_x + WIDTH * CHAR_PX + RIGHT_MARGIN)}px'
    root.set('width', pixel_width)
    for rect in root.iter(SVG + 'rect'):
        rect.set('width', pixel_width)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return problems


if __name__ == '__main__':
    for f in FILES:
        issues = align_file(f)
        print(f'{f}: aligned' if not issues else f'{f}: aligned, except:')
        for label, over in issues:
            print(f'   needs {over} more character(s) of width: {label}  (raise WIDTH or shorten the text)')

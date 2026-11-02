"""
Rewriting the translation on a page of a document: the original text is erased with the colour of the paper and the
translation is written in the same place, in the colour of the original text and at a size that fits. It is what a
translated book or manual should look like, instead of the dark cards of the overlay.

Only blocks on a plain background are rewritten; text over a picture, or in tall narrow columns (vertical text), keeps
the cards, which stay readable on anything. The decision is made block by block from the pixels of the page.
"""
import numpy as np
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QFontMetricsF

from ui.card_render import FONT_FAMILIES, union_box

RING = 4  # px of the ring around a block that is looked at to know what the paper is like
PLAIN_SHARE = 0.85  # share of the ring that must be within PLAIN_DISTANCE of its median colour
PLAIN_DISTANCE = 36
INK_DISTANCE = 90  # a pixel this far from the paper is ink
MIN_PX = 7  # the smallest text that is still worth writing
LOOK_AHEAD = 4  # px looked at beyond a block's edge for the letters its box missed
VERTICAL_RATIO = 2.2  # a block taller than this many times its width is a column of vertical text


def _luma(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def block_rect(item, width, height):
    """Integer rectangle (x1, y1, x2, y2) of a block inside the page, or None."""
    box = union_box([item])
    if box is None:
        return None
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return (x1, y1, x2, y2) if x2 - x1 >= 4 and y2 - y1 >= 4 else None


def paper_of(image, rect):
    """
    (median colour of the ring around the block, True if the paper is plain there). The ring has four sides; three plain
    ones are enough, because a link's underline or a rule runs along a side of the text and is no picture.
    """
    h, w = image.shape[:2]
    x1, y1, x2, y2 = rect
    ax1, ay1, ax2, ay2 = max(0, x1 - RING), max(0, y1 - RING), min(w, x2 + RING), min(h, y2 + RING)
    mask = np.ones((ay2 - ay1, ax2 - ax1), dtype=bool)
    mask[y1 - ay1:y2 - ay1, x1 - ax1:x2 - ax1] = False  # only the ring, not the block itself
    region = image[ay1:ay2, ax1:ax2].astype(np.int16)
    ring = region[mask]
    if len(ring) < 8:
        return None, False
    median = np.median(ring, axis=0)
    close = np.abs(region - median).max(axis=2) <= PLAIN_DISTANCE
    sides = []
    for top, bottom, left, right in ((0, y1 - ay1, 0, ax2 - ax1), (y2 - ay1, ay2 - ay1, 0, ax2 - ax1),
                                     (y1 - ay1, y2 - ay1, 0, x1 - ax1), (y1 - ay1, y2 - ay1, x2 - ax1, ax2 - ax1)):
        strip = close[top:bottom, left:right]
        sides.append(strip.size == 0 or bool(strip.mean() >= PLAIN_SHARE + 0.05))  # the page edge has no strip to judge
    return tuple(int(v) for v in median), sum(sides) >= 3


def grow_to_ink(image, rect, paper):
    """
    The box of a text layer is sometimes smaller than the text it describes (a run whose box misses the first or the last
    letters). Grows the block sideways while there is ink right next to it, looking a few pixels ahead because the
    strokes of a letter leave small gaps. Never more than three line heights.
    """
    h, w = image.shape[:2]
    x1, y1, x2, y2 = rect
    paper_arr = np.array(paper, dtype=np.int16)
    limit = 3 * (y2 - y1)

    def ink_columns(xa, xb):
        if xb <= xa or xa < 0 or xb > w:
            return []
        region = image[y1:y2, xa:xb].astype(np.int16)
        return list((np.abs(region - paper_arr).max(axis=2) >= INK_DISTANCE).any(axis=0))

    grown = 0
    while grown < limit and x2 < w:
        ahead = ink_columns(x2, min(w, x2 + LOOK_AHEAD))
        if not any(ahead):
            break
        step = max(i for i, has in enumerate(ahead) if has) + 1
        x2 += step
        grown += step
    grown = 0
    while grown < limit and x1 > 0:
        ahead = ink_columns(max(0, x1 - LOOK_AHEAD), x1)
        if not any(ahead):
            break
        step = len(ahead) - min(i for i, has in enumerate(ahead) if has)
        x1 -= step
        grown += step
    return (x1, y1, x2, y2)


def ink_of(image, rect, paper):
    """
    What the original text looked like: (colour, [(top, bottom) of every line of text]) with the rows relative to the
    page. The colour is the median of the strongest ink pixels; without ink it is black or white, whichever reads on
    the paper.
    """
    x1, y1, x2, y2 = rect
    region = image[y1:y2, x1:x2].astype(np.int16)
    distance = np.abs(region - np.array(paper, dtype=np.int16)).max(axis=2)
    ink = distance >= INK_DISTANCE
    fallback = (0, 0, 0) if _luma(paper) > 140 else (255, 255, 255)
    if not ink.any():
        return fallback, []
    strongest = distance >= np.percentile(distance[ink], 70)
    colour = tuple(int(v) for v in np.median(region[strongest], axis=0))
    rows = ink.sum(axis=1) >= max(1, int(0.004 * (x2 - x1)))
    lines, start, gap = [], None, 0
    for i, has in enumerate(rows):
        if has:
            start = i if start is None else start
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 2:  # a short pause inside a line (accents, descenders) does not end it
                lines.append((y1 + start, y1 + i - gap + 1))
                start, gap = None, 0
    if start is not None:
        lines.append((y1 + start, y1 + len(rows) - gap))
    # An underline or a rule is a thin stroke, not a line of text
    tallest = max((b - a for a, b in lines), default=0)
    lines = [(a, b) for a, b in lines if b - a > max(3, 0.25 * tallest)]
    return colour, lines


def original_size(lines, rect_height):
    """Font size, in pixels, of the original text, from how its lines are spaced."""
    if len(lines) >= 2:
        pitch = float(np.median(np.diff([top for top, _ in lines])))
        return max(MIN_PX, pitch / 1.35)
    if lines:
        # One line: the ink is shorter than the letters' size when there are no capitals or descenders, and the box
        # (the text layer's, the OCR's) is about as tall as the line: whichever says more is closer to the truth
        return max(MIN_PX, (lines[0][1] - lines[0][0]) * 1.3, rect_height * 1.0)
    return max(MIN_PX, rect_height * 0.8)


def snap_to_body(sizes, line_counts):
    """
    A single line is measured from little ink, so its size is only approximate: when it is close to the body text of the
    page (a contents entry) it takes the body size, which is measured from many lines. Headings and small print (a
    footnote) are clearly different and keep their own size.
    """
    body_sizes = [s for s, n in zip(sizes, line_counts) if n >= 2] or sizes
    body = float(np.median(body_sizes))
    snapped = [body if n <= 1 and 0.85 * body <= s <= 1.15 * body else s for s, n in zip(sizes, line_counts)]
    return snapped, body


def _font(px, bold=False):
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(max(1, int(px)))
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def fit(text, width, avail_h, base_px, floor_px, bold, flags):
    """The largest font from base_px down to floor_px whose wrapped text fits width x avail_h: (font, height, fits)."""
    px = int(base_px)
    while True:
        font = _font(px, bold)
        height = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 100000), flags, text).height()
        if height <= avail_h:
            return font, height, True
        if px <= floor_px:
            return font, height, False
        px -= 1


def _room_below(rect, rects, page_h):
    """How far down a block can grow: until the next block that shares its columns, or the bottom margin."""
    x1, y1, x2, y2 = rect
    limit = page_h - 8
    for other in rects:
        if other is rect or other[1] < y2 - 2:
            continue
        if min(x2, other[2]) - max(x1, other[0]) > 0.3 * min(x2 - x1, other[2] - other[0]):
            limit = min(limit, other[1] - 2)
    return max(limit, y2)


def _room_sides(rect, rects, page_w):
    """How far a block can grow to the left and to the right: until its neighbours on the same rows, or the margins."""
    x1, y1, x2, y2 = rect
    left, right = 8, page_w - 8
    for other in rects:
        if other is rect or min(y2, other[3]) - max(y1, other[1]) <= 0.3 * (y2 - y1):
            continue  # not on the same rows
        if other[2] <= x1:
            left = max(left, other[2] + 2)
        elif other[0] >= x2:
            right = min(right, other[0] - 2)
    return min(left, x1), max(right, x2)


def rewrite_blocks(qimage, image, items):
    """
    Paints the rewritten translation on `qimage` (a copy of the page, of which `image` is the array) for the blocks that
    can take it. Returns the items that could not (busy background, vertical text, a translation that does not fit even
    in small letters): they still need a card.

    The body text of the page gets ONE size, so the page looks like a page: the largest size at which the blocks that
    need the most room still fit (a paragraph or two that are much longer than the rest do not shrink the whole page).
    Headings keep their proportion to the body.
    """
    from PyQt6.QtGui import QPainter
    h, w = image.shape[:2]
    blocks = []
    leftover = []
    for item in items:
        text = (item.get('translation') or '').strip()
        if item.get('is_name') or not text:
            continue
        rect = block_rect(item, w, h)
        if rect is None:
            leftover.append(item)
            continue
        paper, plain = paper_of(image, rect)
        if paper is not None:
            rect = grow_to_ink(image, rect, paper)  # the box may miss the first or last letters of the line
            paper, plain = paper_of(image, rect)
        x1, y1, x2, y2 = rect
        if not plain or (y2 - y1) > VERTICAL_RATIO * (x2 - x1):
            leftover.append(item)
            continue
        colour, lines = ink_of(image, rect, paper)
        blocks.append({'item': item, 'text': text, 'rect': rect, 'paper': paper, 'colour': colour, 'lines': lines,
                       'size': original_size(lines, y2 - y1)})
    if not blocks:
        return leftover

    rects = [b['rect'] for b in blocks] + [r for r in (block_rect(i, w, h) for i in leftover) if r]
    sizes, body = snap_to_body([b['size'] for b in blocks], [len(b['lines']) for b in blocks])
    flags_wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)

    # 1. What each block can have: its own width (a single line may use the free space beside it) and the room below it
    for b, size in zip(blocks, sizes):
        b['size'] = size
        x1, y1, x2, y2 = b['rect']
        single = len(b['lines']) <= 1
        b['heading'] = single and size > 1.25 * body
        b['centred'] = single and abs((x1 + x2) / 2 - w / 2) < 0.04 * w
        left, right = _room_sides(b['rect'], rects, w)
        if single and b['centred']:
            half = min((x1 + x2) / 2 - left, right - (x1 + x2) / 2)
            b['span'] = (int((x1 + x2) / 2 - half), int((x1 + x2) / 2 + half))
        elif single:
            b['span'] = (x1, right)
        else:
            b['span'] = (x1, x2)
        room = _room_below(b['rect'], rects, h) - y1
        # first inside the block's own box (not much smaller than the original), then growing down into the free space
        width = b['span'][1] - b['span'][0]
        font, _, fits = fit(b['text'], width, y2 - y1, size, max(MIN_PX, 0.6 * size), b['heading'], flags_wrap)
        if not fits:
            font, _, fits = fit(b['text'], width, max(room, y2 - y1), size, MIN_PX, b['heading'], flags_wrap)
        b['fits'], b['fit_px'] = fits, font.pixelSize()

    # A translation that does not fit even at the smallest readable size gets a card, which shows all of it
    leftover.extend(b['item'] for b in blocks if not b['fits'])
    blocks = [b for b in blocks if b['fits']]
    if not blocks:
        return leftover

    # 2. One size for the body of the page
    body_fits = [b['fit_px'] for b in blocks if not b['heading']] or [b['fit_px'] for b in blocks]
    body_px = max(float(np.percentile(body_fits, 20)), 0.8 * float(np.median(body_fits)))

    painter = QPainter(qimage)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    try:
        for b in blocks:
            x1, y1, x2, y2 = b['rect']
            sx1, sx2 = b['span']
            width = sx2 - sx1
            px = min(b['fit_px'], int(body_px * (b['size'] / body if b['heading'] else 1.0)))
            font = _font(max(MIN_PX, px), b['heading'])
            text_h = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 100000), flags_wrap, b['text']).height()
            pad = max(2, int(0.12 * b['size'] * 1.35))
            top = y1
            erase = QRectF(min(x1, sx1) - pad, top - pad, max(x2, sx2) - min(x1, sx1) + 2 * pad, max(y2 - y1, text_h) + 2 * pad)
            painter.fillRect(erase, QColor(*b['paper']))
            painter.setFont(font)
            painter.setPen(QColor(*b['colour']))
            align = Qt.AlignmentFlag.AlignHCenter if b['centred'] else Qt.AlignmentFlag.AlignLeft
            painter.drawText(QRectF(sx1, top, width, max(y2 - y1, text_h)),
                             int(align | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), b['text'])
    finally:
        painter.end()
    return leftover

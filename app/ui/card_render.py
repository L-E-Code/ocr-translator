"""
Translation cards: layout and painting shared by the overlay (on screen) and the file export (on an image).

`build_scene(s)` turns the translated items of one reading into positioned cards; `paint_card` / `paint_scene` draw
one on any QPainter. The overlay keeps its own animation state and calls these functions with the animated values.
"""
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPen

PLACEHOLDER = "[Translating with AI...]"
JP_RE = re.compile(r'[぀-ゟ゠-ヿ一-龯]')

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Arial"]

# Palette (dark glass with cyan/violet accent; speaker in amber)
BG_TOP = QColor(20, 27, 45, 240)
BG_BOTTOM = QColor(12, 17, 31, 240)
EDGE = QColor(255, 255, 255, 38)
ACCENT_A = QColor(56, 189, 248)
ACCENT_B = QColor(139, 125, 250)
SPEAKER = QColor(251, 191, 36)
TEXT = QColor(244, 247, 252)

CARD_RADIUS = 12.0
SHADOW_MARGIN = 28


@dataclass
class Chip:
    rect: QRectF
    text: str
    loading: bool
    font: QFont


@dataclass
class Scene:
    """Computed layout of one card (target positions, before any animation)."""
    card: QRectF
    text_rect: QRectF
    text: str
    font: QFont
    flags: int
    loading: bool
    skeleton_lines: int
    chip: Optional[Chip]


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------
def make_font(pt, weight=QFont.Weight.DemiBold, pixels=False):
    """
    Font of `pt` points. With `pixels` the size is fixed in pixels (96 dpi equivalent), which keeps the same look on an
    exported image whatever the screen scaling of the machine is (a point size follows the DPI of the paint device).
    """
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    if pixels:
        font.setPixelSize(max(1, round(float(pt) * 96 / 72)))
    else:
        font.setPointSizeF(float(pt))
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def fit_text(text, width, budget_h, max_pt, min_pt, flags, pixels=False):
    """Largest font (between max_pt and min_pt) whose wrapped text fits in budget_h."""
    height = 0.0
    font = make_font(min_pt, pixels=pixels)
    for pt in range(max_pt, min_pt - 1, -1):
        font = make_font(pt, pixels=pixels)
        height = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 10000), flags, text).height()
        if height <= budget_h:
            break
    return font, height


def union_box(items):
    xs, ys = [], []
    for it in items:
        for pt in (it.get('box') or []):
            xs.append(pt[0])
            ys.append(pt[1])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def build_scene(items, width, height, pad_x, compact=False, pixels=False):
    """Card for one block of dialogue (plus its speaker tab) over an area of width x height. None if nothing to show."""
    speakers = [it for it in items if it.get('is_name')]
    dialogue = [it for it in items if not it.get('is_name')]
    # Speaker only, no dialogue: treats the item as dialogue
    if not dialogue and speakers:
        dialogue, speakers = speakers, []

    translated = [it.get('translation', '').strip() for it in dialogue if it.get('translation')]
    if not translated:
        return None
    text = " ".join(translated)
    loading = PLACEHOLDER in text

    box = union_box(dialogue)
    if box is None:
        box = (width * 0.15, height * 0.72, width * 0.85, height * 0.85)
    ox1, oy1, ox2, oy2 = box
    orig_w = max(20.0, ox2 - ox1)
    orig_h = max(20.0, oy2 - oy1)

    pad_y = pad_x * 0.6  # 20 -> 12, the original proportion
    inset_left = 8.0  # space for the accent bar

    flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.TextFlag.TextWordWrap)
    # Several blocks on screen (menu options): the card hugs its own text instead of the dialogue minimum width
    card_w = min(max(orig_w + 2 * pad_x, 150.0 if compact else 380.0), width - 48)
    text_w = card_w - 2 * pad_x - inset_left
    budget = max(orig_h * 1.35, 56.0)
    font, text_h = fit_text(text, text_w, budget, 20, 12, flags, pixels)
    # Covers the original box and centers the card on it
    # Menu options: the detected boxes are taller than the glyphs, so the card follows the text instead
    card_h = text_h + 2 * pad_y if compact else max(text_h + 2 * pad_y, orig_h + 10)
    card_x = ox1 - pad_x
    card_y = (oy1 + oy2) / 2 - card_h / 2
    line_h = QFontMetricsF(font).lineSpacing()
    lines = max(1, min(3, round(orig_h / max(line_h, 1.0))))

    margin = 16.0
    card_x = min(max(card_x, margin), width - card_w - margin)
    card_y = min(max(card_y, margin), height - card_h - margin)
    card = QRectF(card_x, card_y, card_w, card_h)
    text_rect = QRectF(card_x + pad_x + inset_left, card_y + pad_y, text_w, card_h - 2 * pad_y)

    chip = build_chip(speakers, card, width, height, pixels)
    return Scene(card, text_rect, text, font, flags, loading, lines, chip)


def build_chip(speakers, card, width, height, pixels=False):
    if not speakers:
        return None
    sp = speakers[0]
    orig = sp.get('original', '').strip()
    trans = sp.get('translation', '').strip() or orig
    if not trans:
        return None
    loading = trans == PLACEHOLDER
    label = "···" if loading else trans

    # A name the game already shows in Latin letters does not need to be covered
    if not loading:
        if not JP_RE.search(orig) or orig.lower() == trans.lower():
            return None

    font = make_font(10.5, QFont.Weight.Bold, pixels)
    text_w = QFontMetricsF(font).horizontalAdvance(label)
    chip_h = 28.0
    chip_w = text_w + 30.0

    box = union_box([sp])
    if box is not None:
        x1, y1, x2, y2 = box
        chip_w = max(chip_w, x2 - x1 + 20.0)
        chip_h = max(chip_h, y2 - y1 + 8.0)
        x = x1 - 10.0
        y = (y1 + y2) / 2 - chip_h / 2
    else:
        # Tab over the card's top-left corner
        x = card.left() + 14.0
        y = card.top() - chip_h + 6.0

    x = min(max(x, 10.0), width - chip_w - 10.0)
    y = min(max(y, 10.0), height - chip_h - 10.0)
    return Chip(QRectF(x, y, chip_w, chip_h), label, loading, font)


def separate_cards(scenes, gap=4.0):
    """Trims the cards that would overlap vertically (tightly stacked options), splitting the overlap between them."""
    scenes.sort(key=lambda s: s.card.top())
    for upper, lower in zip(scenes, scenes[1:]):
        a, b = upper.card, lower.card
        if a.right() <= b.left() or b.right() <= a.left():
            continue
        overlap = a.bottom() - b.top() + gap
        if overlap <= 0:
            continue
        cut = overlap / 2
        for scene, top_cut, bottom_cut in ((upper, 0.0, cut), (lower, cut, 0.0)):
            c = scene.card
            scene.card = QRectF(c.left(), c.top() + top_cut, c.width(), max(24.0, c.height() - top_cut - bottom_cut))
            t = scene.text_rect
            scene.text_rect = QRectF(t.left(), t.top() + top_cut, t.width(), max(12.0, t.height() - top_cut - bottom_cut))


def build_scenes(items, width, height, pad_x, pixels=False):
    """One scene per block of text (menus, buttons); a single scene for a plain dialogue."""
    speakers = [it for it in items if it.get('is_name')]
    dialogue = [it for it in items if not it.get('is_name')]
    if len(dialogue) < 2:
        scene = build_scene(items, width, height, pad_x, pixels=pixels)
        return [scene] if scene is not None else []
    scenes = []
    for i, item in enumerate(dialogue):
        scene = build_scene([item] + (speakers if i == 0 else []), width, height, pad_x, compact=True, pixels=pixels)
        if scene is not None:
            scenes.append(scene)
    separate_cards(scenes)
    return scenes


def build_document_scenes(items, width, height, pad_x, pixels=False):
    """
    One card per block of a document page. Each card covers its original block and the font is fitted to that block's
    box (the largest size, up to 20 pt, whose wrapped translation fits); if even the smallest does not fit, the card
    grows downward just enough. There is no speaker tab: a document has no speakers.
    """
    margin = 4.0
    inset = 8.0  # room for the accent bar
    px = min(pad_x, 12.0)
    py = px * 0.5
    flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.TextFlag.TextWordWrap)
    scenes = []
    for item in items:
        text = (item.get('translation') or '').strip()
        box = union_box([item])
        if item.get('is_name') or not text or box is None:
            continue
        x1, y1, x2, y2 = box
        card_w = min(max(x2 - x1 + 2 * px * 0.5, 80.0), width - 2 * margin)
        text_w = card_w - px - inset - px * 0.5
        font, text_h = fit_text(text, text_w, max(y2 - y1 - 2 * py, 10.0), 20, 8, flags, pixels)
        card_h = max(y2 - y1 + 2 * py, text_h + 2 * py)
        card_x = min(max(x1 - px * 0.5, margin), width - card_w - margin)
        card_y = min(max(y1 - py, margin), max(margin, height - card_h - margin))
        card = QRectF(card_x, card_y, card_w, card_h)
        text_rect = QRectF(card_x + px + inset, card_y + py, text_w, card_h - 2 * py)
        scenes.append(Scene(card, text_rect, text, font, flags, False, 1, None))
    return scenes


# ----------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------
def paint_card(painter, scene, card, alpha, text_alpha, bg_opacity, text_color, phase=0.0):
    """
    Draws a scene with its card at `card` (the overlay slides it, so it may differ from scene.card). `alpha` is the
    fade of the whole card, `text_alpha` the fade-in of the text; `bg_opacity` (the opacity setting) only affects the
    backgrounds, never the text. `phase` animates the loading skeleton.
    """
    painter.setOpacity(alpha * bg_opacity)
    draw_panel(painter, card, with_accent=True)
    painter.setOpacity(alpha)

    if scene.loading:
        draw_skeleton(painter, card, scene, phase)
    else:
        # The text is positioned relative to the current card so it does not "shake" during the slide
        shift = card.center() - scene.card.center()
        text_rect = scene.text_rect.translated(shift)
        painter.setFont(scene.font)
        painter.setOpacity(alpha * text_alpha)
        painter.setPen(QColor(0, 0, 0, 150))
        painter.drawText(text_rect.translated(0, 1.2), scene.flags, scene.text)
        painter.setPen(text_color)
        painter.drawText(text_rect, scene.flags, scene.text)

    if scene.chip:
        painter.setOpacity(alpha)
        draw_chip(painter, scene.chip, bg_opacity)


def paint_scene(painter, scene, bg_opacity, text_color, alpha=1.0, phase=0.0):
    """A scene where it was laid out, with no animation."""
    paint_card(painter, scene, scene.card, alpha, 1.0, bg_opacity, text_color, phase)


def draw_panel(painter, rect, with_accent):
    painter.setPen(Qt.PenStyle.NoPen)

    # Soft layered shadow
    opacity = painter.opacity()
    for grow, alpha in ((16, 7), (11, 11), (7, 16), (3, 24)):
        painter.setOpacity(opacity * alpha / 255.0 * 4.0)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow + 4, grow, grow + 4),
                                CARD_RADIUS + grow, CARD_RADIUS + grow)
    painter.setOpacity(opacity)

    # Dark glass body
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, BG_TOP)
    grad.setColorAt(1.0, BG_BOTTOM)
    painter.setBrush(grad)
    painter.setPen(QPen(EDGE, 1.0))
    painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

    if with_accent:
        painter.setPen(Qt.PenStyle.NoPen)
        bar = QRectF(rect.left() + 9, rect.top() + 11, 3.5, max(8.0, rect.height() - 22))
        accent = QLinearGradient(bar.topLeft(), bar.bottomLeft())
        accent.setColorAt(0.0, ACCENT_A)
        accent.setColorAt(1.0, ACCENT_B)
        painter.setBrush(accent)
        painter.drawRoundedRect(bar, 1.75, 1.75)


def draw_skeleton(painter, card, scene, phase):
    """Pulsing gray lines while the translation has not arrived."""
    shift = card.center() - scene.card.center()
    area = scene.text_rect.translated(shift)
    lines = scene.skeleton_lines
    bar_h = 9.0
    gap = 11.0
    total = lines * bar_h + (lines - 1) * gap
    top = area.center().y() - total / 2
    widths = [1.0, 0.72, 0.5]

    painter.setPen(Qt.PenStyle.NoPen)
    span = area.width()
    center_x = area.left() + (phase * 1.6 - 0.3) * span
    for i in range(lines):
        w = area.width() * widths[i % len(widths)]
        bar = QRectF(area.left(), top + i * (bar_h + gap), w, bar_h)
        grad = QLinearGradient(center_x - span * 0.25, 0, center_x + span * 0.25, 0)
        grad.setColorAt(0.0, QColor(148, 163, 184, 55))
        grad.setColorAt(0.5, QColor(186, 230, 253, 150))
        grad.setColorAt(1.0, QColor(148, 163, 184, 55))
        painter.setBrush(grad)
        painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)


def draw_chip(painter, chip, bg_opacity=1.0):
    """Name tab; bg_opacity only scales its background, the name stays fully opaque."""
    rect = chip.rect
    opacity = painter.opacity()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setOpacity(opacity * bg_opacity * 0.35)
    painter.setBrush(QColor(0, 0, 0))
    painter.drawRoundedRect(rect.adjusted(-3, -1, 3, 5), 10, 10)
    painter.setOpacity(opacity * bg_opacity)

    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor(38, 30, 14, 245))
    grad.setColorAt(1.0, QColor(24, 19, 9, 245))
    painter.setBrush(grad)
    painter.setPen(QPen(QColor(SPEAKER.red(), SPEAKER.green(), SPEAKER.blue(), 170), 1.2))
    painter.drawRoundedRect(rect, rect.height() / 2.2, rect.height() / 2.2)

    painter.setOpacity(opacity)
    painter.setFont(chip.font)
    painter.setPen(SPEAKER)
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), chip.text)


# ----------------------------------------------------------------------
# Export to an image
# ----------------------------------------------------------------------
STYLE_CARD = "card"    # the overlay look, drawn over the original text
STYLE_STRIP = "strip"  # the page untouched, with a band of translated text underneath


def _to_qimage(image_rgb):
    """RGB numpy array -> QImage of its own (the pixels are copied), at 96 dpi like the pixel-sized fonts."""
    h, w = image_rgb.shape[:2]
    data = np.ascontiguousarray(image_rgb[:, :, :3])
    qimage = QImage(data.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    qimage.setDotsPerMeterX(3780)
    qimage.setDotsPerMeterY(3780)
    return qimage


def _to_array(qimage):
    qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
    h, w = qimage.height(), qimage.width()
    ptr = qimage.constBits()
    ptr.setsize(qimage.bytesPerLine() * h)
    rows = np.frombuffer(ptr, dtype=np.uint8).reshape(h, qimage.bytesPerLine())
    return rows[:, :w * 3].reshape(h, w, 3).copy()


def _paint_cards(qimage, items, bg_opacity, text_color, pad_x, document=False):
    painter = QPainter(qimage)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    build = build_document_scenes if document else build_scenes
    for scene in build(items, qimage.width(), qimage.height(), pad_x, pixels=True):
        if document:
            # The glass of the overlay lets a little of what is under it through, which on a white page leaves the
            # original text readable: a solid base hides it (the opacity setting still lets it show on purpose)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_TOP.red(), BG_TOP.green(), BG_TOP.blue()))
            painter.setOpacity(bg_opacity)
            painter.drawRoundedRect(scene.card, CARD_RADIUS, CARD_RADIUS)
            painter.setOpacity(1.0)
        paint_scene(painter, scene, bg_opacity, text_color)
    painter.end()
    return qimage


def _paint_strip(qimage, items, text_color, pad_x, document=False):
    """
    The page with a band underneath: the speaker (if any) in amber, then the translated text. For a document the band
    holds every block, one paragraph per line, and grows as tall as the text needs.
    """
    width = qimage.width()
    speakers = [it for it in items if it.get('is_name') and it.get('translation')]
    dialogue = [it for it in items if not it.get('is_name') and it.get('translation')]
    text = ("\n" if document else " ").join(it['translation'].strip() for it in dialogue)
    if not text:
        return qimage

    margin = max(12.0, pad_x)
    flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
    text_w = width - 2 * margin - 8.0
    font, text_h = fit_text(text, text_w, max(220.0, qimage.height()) if document else 220.0, 16 if document else 20, 12, flags, pixels=True)
    name = speakers[0]['translation'].strip() if speakers else ""
    name_font = make_font(10.5, QFont.Weight.Bold, pixels=True)
    name_h = QFontMetricsF(name_font).lineSpacing() + 4.0 if name else 0.0
    strip_h = int(text_h + name_h + 2 * margin * 0.6 + 1)

    canvas = QImage(width, qimage.height() + strip_h, QImage.Format.Format_RGB888)
    canvas.setDotsPerMeterX(3780)
    canvas.setDotsPerMeterY(3780)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.drawImage(0, 0, qimage)
    band = QRectF(0, qimage.height(), width, strip_h)
    grad = QLinearGradient(band.topLeft(), band.bottomLeft())
    grad.setColorAt(0.0, BG_TOP.lighter(100))
    grad.setColorAt(1.0, BG_BOTTOM)
    painter.fillRect(band, QColor(BG_TOP.red(), BG_TOP.green(), BG_TOP.blue()))
    painter.fillRect(band, grad)
    pad_y = margin * 0.6
    accent = QLinearGradient(QPointF(0, band.top()), QPointF(0, band.bottom()))
    accent.setColorAt(0.0, ACCENT_A)
    accent.setColorAt(1.0, ACCENT_B)
    painter.fillRect(QRectF(margin * 0.5, band.top() + pad_y, 3.5, strip_h - 2 * pad_y), accent)

    y = band.top() + pad_y
    x = margin + 8.0
    if name:
        painter.setFont(name_font)
        painter.setPen(SPEAKER)
        painter.drawText(QRectF(x, y, text_w, name_h), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
        y += name_h
    painter.setFont(font)
    painter.setPen(text_color)
    painter.drawText(QRectF(x, y, text_w, text_h), flags, text)
    painter.end()
    return canvas


def render_page(image_rgb, items, style=STYLE_CARD, bg_opacity=1.0, text_color=None, pad_x=20.0, document=False,
                rewrite=True):
    """
    The page as an RGB array with the translation drawn on it, with the look of the overlay. `items` are the results of
    `OCRTranslator.process_image` (boxes in page coordinates). STYLE_STRIP returns a taller image (the band is added
    underneath). Without any translated text the page comes back unchanged. `document` is for pages with many blocks of
    text: the blocks on a plain background are rewritten in place (the original erased, the translation written in its
    colour; `rewrite=False` turns that off) and the others get one card each, with the font fitted to the block.
    """
    color = text_color if isinstance(text_color, QColor) and text_color.isValid() else QColor(text_color or TEXT)
    if not color.isValid():
        color = QColor(TEXT)
    qimage = _to_qimage(image_rgb)
    if style == STYLE_STRIP:
        qimage = _paint_strip(qimage, items, color, float(pad_x), document)
    else:
        if document and rewrite:
            from ui import page_rewrite
            items = page_rewrite.rewrite_blocks(qimage, image_rgb, items)  # what could not be rewritten keeps a card
        qimage = _paint_cards(qimage, items, bg_opacity, color, float(pad_x), document)
    return _to_array(qimage)

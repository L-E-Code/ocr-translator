"""How a page is read: the two modes shared by the OCR engines and the batch translation."""

# One dialogue block plus its speaker (what the live mode and screenshots of a dialogue box need): the engine keeps
# the dominant block of text and treats the rest as scenery
MODE_DIALOGUE = "dialogue"

# Every block of text on the page (paragraphs, headings, captions), in reading order, with no speaker: PDFs, comic pages
MODE_DOCUMENT = "document"

MODES = (MODE_DIALOGUE, MODE_DOCUMENT)

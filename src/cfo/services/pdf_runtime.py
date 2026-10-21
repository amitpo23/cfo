"""PDFium is not thread-safe: serialize native work within each app process."""
from threading import RLock

PDFIUM_LOCK = RLock()

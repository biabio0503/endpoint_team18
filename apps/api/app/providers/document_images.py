"""Bounded, in-memory image preparation. PDFium calls are serialized per process."""
from contextlib import closing
from io import BytesIO
import threading
import warnings

from providers.google_vision_ocr import OCRError

MAX_EDGE = 2000
MAX_SOURCE_PIXELS = 20000000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_pdfium_lock = threading.Lock()


def _png(image, *, skip_blank=False):
    from PIL import Image
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    # DOCX PNGs often contain black lettering on a transparent background.
    # Dropping alpha would turn that background black and hide the text.
    with Image.new('RGB', image.size, 'white') as normalized:
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            with image.convert('RGBA') as rgba:
                with rgba.getchannel('A') as alpha:
                    normalized.paste(rgba, mask=alpha)
        else:
            normalized.paste(image)
        if skip_blank and all(low >= 250 for low, high in normalized.getextrema()):
            return None
        output = BytesIO()
        normalized.save(output, format='PNG')
    content = output.getvalue()
    if len(content) > MAX_IMAGE_BYTES:
        raise OCRError('ocr_image_error')
    return content


def pdf_page_image(data, index):
    import pypdfium2 as pdfium
    try:
        with _pdfium_lock, closing(pdfium.PdfDocument(data)) as pdf:
            with closing(pdf[index]) as page:
                width, height = page.get_size()
                if min(width, height) <= 0:
                    raise ValueError('invalid page size')
                scale = min(2, MAX_EDGE / max(width, height))
                with closing(page.render(scale=scale)) as bitmap:
                    with bitmap.to_pil() as image:
                        return _png(image, skip_blank=True)
    except Exception:
        raise OCRError('ocr_image_error') from None


def docx_image(data):
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > MAX_SOURCE_PIXELS or getattr(image, 'n_frames', 1) > 1:
                    raise ValueError('image bounds')
                return _png(image)
    except Exception:
        raise OCRError('ocr_image_error') from None

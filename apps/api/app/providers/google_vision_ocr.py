"""One image, one DOCUMENT_TEXT_DETECTION request. No SDK retries or text rewriting."""
import json
import os
from pathlib import Path

REQUEST_TIMEOUT = 25
MAX_OCR_TEXT = 1000000
MESSAGES = {
    'ocr_disabled': '현재 OCR 기능 이용 불가: 이미지 글자를 읽지 않았습니다.',
    'ocr_credentials_missing': '현재 OCR 기능 이용 불가: 서버 인증이 설정되지 않았습니다.',
    'ocr_credentials_invalid': '현재 OCR 기능 이용 불가: 서버 인증 설정을 확인해야 합니다.',
    'ocr_auth_error': '현재 OCR 기능 이용 불가: 서버 인증 또는 권한을 확인해야 합니다.',
    'ocr_quota_exceeded': 'OCR 제공자의 사용량 제한으로 읽지 못했습니다.',
    'ocr_budget_exceeded': 'OCR 사용량 제한 안내: 이번 미국 태평양 시간 기준 월의 처리 한도에 도달했습니다.',
    'ocr_document_limit': '문서당 OCR 페이지·이미지 처리 한도에 도달했습니다.',
    'ocr_timeout': 'OCR 응답 시간이 초과되었습니다. 중복 호출 방지를 위해 다시 호출하지 않습니다.',
    'ocr_uncertain': '이전 OCR 호출의 완료 여부를 확인할 수 없어 다시 호출하지 않습니다.',
    'ocr_api_error': 'OCR 제공자 오류로 읽지 못했습니다. 같은 이미지는 다시 호출하지 않습니다.',
    'ocr_storage_error': 'OCR 호출 기록을 안전하게 확인하지 못해 처리를 중단했습니다.',
    'ocr_image_error': '이미지 형식·크기 또는 페이지 렌더링 제한으로 읽지 못했습니다.',
    'ocr_result_too_large': 'OCR 결과 크기 제한을 초과하여 읽지 못했습니다.',
    'ocr_empty_text': '이미지를 처리했으나 읽을 수 있는 글자를 찾지 못했습니다.',
}


class OCRError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES.get(code, MESSAGES['ocr_api_error']))


def credential_path():
    explicit = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if explicit:
        return Path(explicit)
    # File-backed ADC only. Do not probe metadata servers when credentials are absent.
    return Path(os.environ.get('CLOUDSDK_CONFIG', Path.home() / '.config/gcloud')) / 'application_default_credentials.json'


def load_credentials():
    try:
        path = credential_path()
        if not path.is_file():
            raise OCRError('ocr_credentials_missing')
        from google.oauth2 import service_account, credentials
        info = json.loads(path.read_text())
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        if info.get('type') == 'service_account':
            return service_account.Credentials.from_service_account_info(info, scopes=scopes)
        if info.get('type') == 'authorized_user':
            return credentials.Credentials.from_authorized_user_info(info, scopes=scopes)
        raise ValueError('unsupported credential type')
    except OCRError:
        raise
    except Exception:
        raise OCRError('ocr_credentials_invalid') from None


def availability():
    from config import ocr_settings
    if ocr_settings()['provider'] != 'google_vision':
        return 'ocr_disabled'
    try:
        load_credentials()  # Local parsing only; no token refresh or remote request.
    except OCRError as error:
        return error.code
    return None


class GoogleVisionOCR:
    def __init__(self, client=None):
        self.client = client

    def detect(self, content):
        from google.cloud import vision
        from google.api_core import exceptions
        from google.auth.exceptions import GoogleAuthError
        try:
            if self.client is None:
                self.client = vision.ImageAnnotatorClient(credentials=load_credentials())
            response = self.client.document_text_detection(
                image=vision.Image(content=content),
                image_context=vision.ImageContext(language_hints=['ko', 'en']),
                retry=None, timeout=REQUEST_TIMEOUT,
            )
            if response.error.code:
                code = {7: 'ocr_auth_error', 16: 'ocr_auth_error', 8: 'ocr_quota_exceeded',
                        4: 'ocr_timeout'}.get(response.error.code, 'ocr_api_error')
                raise OCRError(code)
            text = response.full_text_annotation.text
            if len(text) > MAX_OCR_TEXT:
                raise OCRError('ocr_result_too_large')
            # Preserve full_text_annotation.text verbatim. Match symbol characters
            # to original offsets, allowing only whitespace between symbols.
            segments = []; cursor = 0; number = 0
            for page in response.full_text_annotation.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        number += 1
                        symbols = ''.join(s.text for w in paragraph.words for s in w.symbols)
                        start = cursor; pos = cursor; matched = bool(symbols)
                        while start < len(text) and text[start].isspace(): start += 1
                        for char in symbols:
                            while pos < len(text) and text[pos].isspace() and not char.isspace(): pos += 1
                            if pos >= len(text) or text[pos] != char:
                                matched = False; break
                            pos += 1
                        if matched:
                            segments.append({'start': start, 'end': pos, 'ocr_paragraph': number,
                                'bbox': [[v.x, v.y] for v in paragraph.bounding_box.vertices],
                                'coordinate_space': 'ocr_image_pixels'})
                            cursor = pos
            return {'text': text, 'segments': segments}
        except OCRError:
            raise
        except (exceptions.Unauthenticated, exceptions.PermissionDenied, GoogleAuthError):
            raise OCRError('ocr_auth_error') from None
        except exceptions.ResourceExhausted:
            raise OCRError('ocr_quota_exceeded') from None
        except (exceptions.DeadlineExceeded, TimeoutError):
            raise OCRError('ocr_timeout') from None
        except Exception:
            raise OCRError('ocr_api_error') from None

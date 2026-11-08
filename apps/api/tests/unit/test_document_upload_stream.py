import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from api.domain import Problem
from api.routes import documents


def test_multipart_stream_is_bounded_even_when_content_length_lies(monkeypatch):
    monkeypatch.setattr(documents, 'MAX_DOCUMENT_BYTES', 4)

    class Request:
        headers = {'content-length': '2', 'content-type': 'multipart/form-data; boundary=x'}

        async def stream(self):
            yield b'x' * (65536 + 5)

        def form(self, **kwargs):
            raise AssertionError('oversized body must not be parsed')

    with pytest.raises(Problem) as error:
        asyncio.run(documents.upload_data(Request()))
    assert error.value.status == 413

"""One real Gemini request on synthetic ClassBridge text; no database, files, or OCR APIs."""
import argparse
from functools import partial
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'app'))
    sys.path.insert(0, str(root / 'tests' / 'fixtures'))
    from dotenv import load_dotenv
    load_dotenv(root / '.env', override=False)
    from classbridge import classbridge_document, DETAILS
    from services.project_experience import verify_experiences
    from services.gemini_projects import extract_project_experiences
    from services.gemini_jobs import _generate
    from services.gemini import GeminiError

    report = {'fixture': 'synthetic ClassBridge transcription with scrambled OCR coordinates',
              'model': os.environ.get('GEMINI_MODEL') or 'gemini-3.5-flash', 'max_attempts': 1, 'ocr_calls': 0}
    doc = classbridge_document()
    if not os.environ.get('GEMINI_API_KEY', '').strip():
        report['status'] = 'not_configured'
    else:
        try:
            with patch('services.gemini_projects._generate', partial(_generate, max_attempts=1)):
                model = extract_project_experiences(doc)
            items, errors = verify_experiences(doc, model, 'live-classbridge')
            report.update(status='completed', candidates=len(model.experiences), verified=len(items), errors=errors,
                details={name: any(i['activity'] == quote and i['contribution_scope'] == 'personal' for i in items)
                         for name, quote in DETAILS.items()}, experiences=items, model_response=model.model_dump())
        except GeminiError as exc:
            report.update(status='failed', error_code=exc.code, message=exc.message)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('experiences', 'model_response')}, ensure_ascii=False))
    return 0 if report.get('details') and all(report['details'].values()) and not report['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

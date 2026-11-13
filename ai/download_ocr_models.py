"""Download public OCR models to the gitignored local model directory."""
from pathlib import Path
from huggingface_hub import snapshot_download

base = Path(__file__).resolve().parent / 'models'
for repository, name in [('atonlee/Qota-OCR','qota-ocr'), ('PaddlePaddle/PP-OCRv6_small_det_safetensors','ocr-detector')]:
    snapshot_download(repository, local_dir=base/name, allow_patterns=['*.json','*.safetensors'])
    print(f'{name}: 준비됨')

"""Inference using a locally available instruction model; never downloads weights."""
import json
import os
import sys
from prompt import make_prompt

try:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    model_path = os.environ.get('LOCAL_MODEL_PATH')
    if not model_path: raise ValueError('LOCAL_MODEL_PATH에 로컬 모델 경로를 지정하세요.')
    if not torch.cuda.is_available(): raise ValueError('CUDA GPU를 사용할 수 없습니다.')
    data = json.load(sys.stdin)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True, dtype=torch.float16, device_map='cuda')
    prompt = make_prompt(data)
    messages = [{'role': 'user', 'content': prompt}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    encoded = tokenizer(rendered, return_tensors='pt').input_ids.to('cuda')
    with torch.inference_mode(): output = model.generate(encoded, max_new_tokens=2048, do_sample=False)
    print(tokenizer.decode(output[0][encoded.shape[-1]:], skip_special_tokens=True).strip())
except Exception as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)

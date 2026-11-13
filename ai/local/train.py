"""Fine-tune a local causal LM on curated JSONL messages using the NVIDIA GPU."""
import argparse
import json
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, DataCollatorForLanguageModeling
from peft import LoraConfig, get_peft_model

p = argparse.ArgumentParser()
p.add_argument('--model', required=True, help='로컬 기본 모델 경로')
p.add_argument('--data', required=True, help='검수된 학습 데이터 JSONL 경로')
p.add_argument('--output', required=True, help='학습 결과 저장 경로')
p.add_argument('--epochs', type=int, default=3)
args = p.parse_args()
if not torch.cuda.is_available(): raise RuntimeError('CUDA GPU가 필요합니다. CUDA 지원 PyTorch를 설치하세요.')
tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
if tokenizer.pad_token is None: tokenizer.pad_token = tokenizer.eos_token
model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, dtype=torch.bfloat16)
model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules=['q_proj', 'v_proj'], task_type='CAUSAL_LM'))
model.print_trainable_parameters()
rows = [json.loads(line) for line in open(args.data, encoding='utf-8') if line.strip()]
if not rows or any(not isinstance(row.get('messages'), list) for row in rows): raise ValueError('각 JSONL 행에 messages 배열이 필요합니다.')
texts = [tokenizer.apply_chat_template(row['messages'], tokenize=False, add_generation_prompt=False) for row in rows]
dataset = Dataset.from_dict({'text': texts}).map(lambda batch: tokenizer(batch['text'], truncation=True, max_length=1024, add_special_tokens=False), batched=True, remove_columns=['text'])
def collate(items):
    batch = tokenizer.pad(items, return_tensors='pt')
    labels = batch['input_ids'].clone()
    labels[batch['attention_mask'] == 0] = -100
    batch['labels'] = labels
    return batch
trainer = Trainer(model=model, args=TrainingArguments(output_dir=args.output, per_device_train_batch_size=1, gradient_accumulation_steps=4, num_train_epochs=args.epochs, bf16=True, save_strategy='no', report_to='none', learning_rate=2e-4), train_dataset=dataset, data_collator=collate)
trainer.train(); model.merge_and_unload().save_pretrained(args.output); tokenizer.save_pretrained(args.output)

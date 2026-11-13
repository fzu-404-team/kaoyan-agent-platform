"""Prepare the public cl100k_base vocabulary once; no model, key or business data is used."""
import hashlib
import os
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kaoyan-agent'))
from core.tokens import PROJECT_CACHE, TOKENIZER_FILE, TOKENIZER_SHA, TOKENIZER_URL, verified_vocabulary

# The published file is about 1.7 MB; anything far larger is not that file.
MAX_BYTES = 8 * 1024 * 1024

if __name__ == '__main__':
    if verified_vocabulary() is not None:
        print('已存在校验通过的词表，未下载。')
        raise SystemExit(0)
    # python.org builds on macOS ship without system roots; certifi comes with httpx.
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(TOKENIZER_URL, timeout=30, context=context) as response:
            raw = response.read(MAX_BYTES + 1)
    except OSError as error:
        raise SystemExit(f'词表下载失败（{type(error).__name__}），未写入任何文件。') from None
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != TOKENIZER_SHA:
        raise SystemExit('词表校验未通过，未写入任何文件。')
    PROJECT_CACHE.mkdir(parents=True, exist_ok=True)
    target = PROJECT_CACHE / TOKENIZER_FILE
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(raw)
    os.replace(temporary, target)
    print(f'词表就绪：{target}（{len(raw)}字节，SHA-256已校验）。重启Agent后输入计量使用cl100k_base估算。')

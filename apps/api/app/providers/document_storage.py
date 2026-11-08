"""Private filesystem storage. Keys are server-generated document UUIDs only."""
import os
from pathlib import Path
import re
from config import FILE_STORAGE_PATH

class LocalDocumentStorage:
    def __init__(self, root=FILE_STORAGE_PATH): self.root=Path(root)
    def path(self,key):
        if not re.fullmatch(r'[0-9a-f-]{36}',key): raise ValueError('invalid storage key')
        return self.root/key
    def save(self,key,data):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path(key),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        except BaseException:
            self.delete(key)
            raise
    def read(self,key): return self.path(key).read_bytes()
    def delete(self,key): self.path(key).unlink(missing_ok=True)
    def old_keys(self, cutoff):
        if not self.root.exists(): return []
        return [path.name for path in self.root.iterdir() if re.fullmatch(r'[0-9a-f-]{36}',path.name) and path.is_file() and path.stat().st_mtime<cutoff]


def get_storage():
    return LocalDocumentStorage()

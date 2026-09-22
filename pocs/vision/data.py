"""Download a pinned, small MVTec AD bottle subset. Never commit the images."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import requests
from PIL import Image
from pocs.common.paths import ROOT

DATA=ROOT/'data'/'mvtec-bottle'
REVISION='c75b39616f84db43677bcc8228caaafaf5096d7f'
BASE=f'https://huggingface.co/datasets/foersben/mvtec-ad/resolve/{REVISION}/bottle/'
CATEGORIES=('good','broken_large','broken_small','contamination')

def paths():
    files=[f'train/good/{i:03d}.png' for i in range(40)]
    for kind in CATEGORIES:
        files += [f'test/{kind}/{i:03d}.png' for i in range(8)]
        if kind!='good':files += [f'ground_truth/{kind}/{i:03d}_mask.png' for i in range(8)]
    return files+['license.txt','readme.txt']

def fetch():
    def one(name):
        target=DATA/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            response=requests.get(BASE+name,timeout=(10,60));response.raise_for_status()
            partial=target.with_suffix(target.suffix+'.part');partial.write_bytes(response.content)
            if name.endswith('.png'):
                with Image.open(partial) as im:im.verify()
            partial.replace(target)
        return name,hashlib.sha256(target.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool: hashes=dict(pool.map(one,paths()))
    (DATA/'manifest.json').write_text(json.dumps({'dataset':'MVTec AD bottle','mirror':BASE,
        'revision':REVISION,'license':'CC BY-NC-SA 4.0','sha256':hashes},indent=2),encoding='utf-8')
    print(f'Dataset ready: {DATA} ({len(hashes)} files)',flush=True)

def samples():
    return [DATA/f'test/{kind}/{i:03d}.png' for i in range(8) for kind in CATEGORIES]

if __name__=='__main__':fetch()

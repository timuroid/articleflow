"""Download registered public DOCX fixtures; verify pinned SHA-256 before use."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
from zipfile import ZipFile


def download(manifest, output):
    output.mkdir(parents=True,exist_ok=True)
    for row in json.loads(manifest.read_text())['documents']:
        if row['status']!='downloaded':continue
        destination=output/(row['id']+'.docx')
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('EXISTING_SOURCE_HASH_MISMATCH')
            print(row['id']+': verified existing');continue
        with urlopen(quote(row['download_url'],safe=':/%?=&'),timeout=45) as response:data=response.read(10000001)
        if len(data)>10000000 or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('REMOTE_SOURCE_CHANGED')
        destination.write_bytes(data)
        with ZipFile(destination) as package:
            if 'word/document.xml' not in package.namelist():raise ValueError('NOT_DOCX')
        print(row['id']+': downloaded and verified')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=Path('datasets/real-v027/sources.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();download(args.manifest,args.output)

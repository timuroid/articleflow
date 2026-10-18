"""Out-of-process candidate engine. No generated Python is imported by the supervisor."""
import ast
import contextlib
import contextvars
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from .docx_engine import DocumentError,digest,dump

ACTIVE=contextvars.ContextVar('articleflow_candidate_engine',default=None)
EDITABLE={'catalogue.py','typography019.py','rules023.py','order024.py'}
MAX_ARCHIVE=128*1024*1024

@contextlib.contextmanager
def use(engine):
    token=ACTIVE.set(engine)
    try:yield
    finally:ACTIVE.reset(token)


def file_hashes(directory):
    return {p.name:digest(p.read_bytes()) for p in sorted(Path(directory).glob('*.py'))}


def snapshot(destination,base=None):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False);destination.chmod(0o755)
    for p in Path(base or Path(__file__).parent).glob('*.py'):
        if p.is_symlink():raise DocumentError('ENGINE_SYMLINK')
        shutil.copyfile(p,destination/p.name);(destination/p.name).chmod(0o644)
    return file_hashes(destination)


def propose(base,destination,response):
    if not isinstance(response,dict) or set(response)!={'diagnosis','edits'} or not isinstance(response['diagnosis'],str):raise DocumentError('PATCH_SCHEMA')
    edits=response['edits']
    if not isinstance(edits,list) or not 1<=len(edits)<=12:raise DocumentError('PATCH_COUNT')
    texts={}
    for e in edits:
        if not isinstance(e,dict) or set(e)!={'file','old','new'} or e['file'] not in EDITABLE:raise DocumentError('PATCH_FILE_FORBIDDEN')
        if not all(isinstance(e[k],str) for k in ('old','new')) or not e['old'] or len(e['old'])+len(e['new'])>60000:raise DocumentError('PATCH_SIZE')
        text=texts.get(e['file'],(Path(base)/e['file']).read_text())
        if text.count(e['old'])!=1:raise DocumentError('PATCH_ANCHOR_NOT_UNIQUE')
        texts[e['file']]=text.replace(e['old'],e['new'],1)
    for text in texts.values():
        try:ast.parse(text)
        except (SyntaxError,ValueError,RecursionError):raise DocumentError('PATCH_SYNTAX')
    snapshot(destination,base)
    for name,text in texts.items():(Path(destination)/name).write_text(text)
    return {'before':file_hashes(base),'after':file_hashes(destination),'changed':sorted(texts)}


def unpack(raw,destination):
    if len(raw)>MAX_ARCHIVE:raise DocumentError('WORKER_OUTPUT_LIMIT')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers()
        if len(members)>6000 or sum(m.size for m in members)>MAX_ARCHIVE:raise DocumentError('WORKER_OUTPUT_LIMIT')
        seen=set()
        for m in members:
            p=PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts or m.issym() or m.islnk() or not (m.isdir() or m.isfile()):raise DocumentError('WORKER_UNSAFE_ARCHIVE')
            if p in seen:raise DocumentError('WORKER_DUPLICATE_PATH')
            seen.add(p)
        for m in members:
            p=destination.joinpath(*PurePosixPath(m.name).parts)
            if any(x.is_symlink() for x in [p,*p.parents]):raise DocumentError('WORKER_UNSAFE_ARCHIVE')
            if m.isdir():p.mkdir(parents=True,exist_ok=True)
            else:
                p.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(m) as src,p.open('wb') as out:shutil.copyfileobj(src,out)


class Engine:
    def __init__(self,source,image='articleflow-repair034',timeout=120):
        self.source=Path(source).resolve();self.hashes=file_hashes(self.source);self.timeout=timeout
        self.env={k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'}}
        self.command=['docker','--host=unix:///var/run/docker.sock']
        self.image=self.docker('image','inspect',image,'--format','{{.Id}}').strip()
        if not self.image.startswith('sha256:'):raise DocumentError('WORKER_IMAGE_UNPINNED')
    def docker(self,*args,timeout=30,binary=False):
        try:r=subprocess.run(self.command+list(args),env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        except (OSError,subprocess.TimeoutExpired):raise DocumentError('WORKER_UNAVAILABLE')
        if r.returncode:raise DocumentError('WORKER_DOCKER_FAILED')
        return r.stdout if binary else r.stdout.decode()
    def invoke(self,operation,payload,inputs,destination):
        if file_hashes(self.source)!=self.hashes:raise DocumentError('ENGINE_CHANGED')
        destination=Path(destination)
        if destination.exists():raise DocumentError('WORKER_DESTINATION_EXISTS')
        with tempfile.TemporaryDirectory(prefix='articleflow-worker-') as td:
            work=Path(td)/'input';work.mkdir();work.chmod(0o755)
            for name,path in inputs.items():
                if name not in {'source.docx','template','samples'}:raise DocumentError('WORKER_INPUT_NAME')
                path=Path(path)
                if path.is_symlink() or path.is_dir() and any(p.is_symlink() for p in path.rglob('*')):raise DocumentError('WORKER_INPUT_SYMLINK')
                if path.is_dir():shutil.copytree(path,work/name)
                else:shutil.copyfile(path,work/name)
            dump(work/'task.json',{'operation':operation,'payload':payload})
            for p in work.rglob('*'):
                if p.is_symlink():raise DocumentError('WORKER_INPUT_SYMLINK')
                p.chmod(0o755 if p.is_dir() else 0o644)
            name='articleflow-'+uuid.uuid4().hex
            try:
                self.docker('create','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                    '--pids-limit','64','--memory','1g','--cpus','1','--log-driver','none',
                    '--tmpfs','/tmp:rw,noexec,nosuid,size=64m,mode=1777','--tmpfs','/out:rw,noexec,nosuid,size=128m,mode=1777',
                    '--env','HTTP_PROXY=','--env','HTTPS_PROXY=','--env','ALL_PROXY=',
                    '--env','http_proxy=','--env','https_proxy=','--env','all_proxy=','--env','NO_PROXY=','--env','no_proxy=',
                    '--mount',f'type=bind,src={work},dst=/work,readonly',
                    '--mount',f'type=bind,src={self.source},dst=/engine/articleflow,readonly',self.image)
                self.docker('start',name)
                started=time.monotonic()
                while True:
                    if time.monotonic()-started>self.timeout:raise DocumentError('WORKER_TIMEOUT')
                    try:self.docker('exec',name,'test','-f','/out/_done',timeout=10);break
                    except DocumentError:
                        if self.docker('inspect',name,'--format','{{.State.Running}}').strip()!='true':raise DocumentError('WORKER_EXITED')
                        time.sleep(.2)
                raw=self.docker('exec',name,'tar','-C','/out','-cf','-','.',binary=True)
                unpack(raw,destination)
            finally:
                subprocess.run(self.command+['rm','-f',name],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
        result=json.loads((destination/'worker.json').read_text())
        if result.get('status')!='ok':raise DocumentError('CANDIDATE_'+str(result.get('code','FAILED'))[:100])
        return result.get('value')

"""Explicit transport retries; never regenerate template rules for an HTTP outage."""
import time
from pathlib import Path
from .docx_engine import DocumentError

TRANSIENT={'PROVIDER_HTTP_429','PROVIDER_HTTP_502','PROVIDER_HTTP_503','PROVIDER_HTTP_504'}

def recover(invoke,directory,*,delays=(5,15),sleep=time.sleep,on_retry=None):
    directory=Path(directory)
    for index in range(len(delays)+1):
        attempt=directory if index==0 else directory.with_name(directory.name+f'-transport-{index+1}')
        try:
            value,meta=invoke(attempt)
            return value,{**meta,'transport_attempts':index+1,'response_directory_name':attempt.name}
        except DocumentError as exc:
            if str(exc) not in TRANSIENT or index==len(delays):raise
            if on_retry:on_retry({'code':str(exc),'next_attempt':index+2,'delay_seconds':delays[index]})
            sleep(delays[index])

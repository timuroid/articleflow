"""Optional bounded question window. Timeout is never an answer or approval."""
import time


def wait(questions, initial, provider, emit, *, seconds=30, clock=time.monotonic, wall=time.time, sleep=time.sleep):
    started=clock();deadline=wall()+seconds
    state={'status':'waiting','deadline_unix':deadline,'seconds':seconds,'questions':questions,'initial_revision':initial['revision']}
    emit(dict(state))
    while clock()-started<seconds:
        latest=provider()
        if latest['revision']>initial['revision']:
            state.update(status='answered',waited_seconds=round(clock()-started,3),received_revision=latest['revision']);emit(dict(state));return latest,state
        sleep(min(.25,max(0,seconds-(clock()-started))))
    state.update(status='continued_without_answer',waited_seconds=round(clock()-started,3));emit(dict(state));return initial,state

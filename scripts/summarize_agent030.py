"""Publish only aggregate loop metrics, never source text, model responses or account data."""
import argparse,json
from decimal import Decimal
from pathlib import Path
from articleflow.docx_engine import dump

def summarize(folder):
    summary=json.loads((folder/'summary.json').read_text())
    for row in summary['documents']:
        report=json.loads((folder/row['id']/'result.json').read_text())
        metadata=[json.loads(p.read_text()) for p in (folder/row['id']).rglob('meta.json')]
        row['api_seconds_sum']=sum(m.get('seconds',0) for m in metadata)
        row['unknown_cost_attempts']=sum(m.get('api_attempts',0) for m in metadata if m.get('cost_usd') is None)
        row['unconfirmed_reserve_usd']=str(sum((Decimal(str(m.get('reserve_usd') or 0)) for m in metadata if m.get('api_attempts') and m.get('cost_usd') is None),Decimal(0)))
        row['human_feedback_revisions_applied']=report.get('feedback_revision_applied',0)
        for public,private in zip(row['iterations'],report.get('iterations',[])):
            apps=private.get('applications',[])
            public['application_failures']=[a['code'] for a in apps if a.get('code')]
            public['unresolved_count']=sum(len(a.get('unresolved',[])) for a in apps)
            public['teacher_student_agreement']={'correct':sum(a.get('role_correct',0) for a in apps),'total':sum(a.get('role_total',0) for a in apps),'independent_ground_truth':False}
            public['generated_questions']=len(private.get('questions',[]))
        row['instance_replay_passed']=all(p.get('status')=='instance_verified' for p in report.get('preparation',[])) and bool(report.get('preparation'))
    summary['timing_note']='Wall time includes local rendering and waiting on the shared ledger; API seconds sum excludes lock waiting and account/catalog requests. Series029,030 and031 overlapped. Do not treat wall times as isolated service latency.'
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();dump(a.output,summarize(a.run))

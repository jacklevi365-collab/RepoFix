"""Docker proof of safe round-boundary continuation, with zero model calls."""
from pathlib import Path
from repofix.runs import RunSpec,run_task,resume_task

root=Path(__file__).resolve().parents[1]
first=run_task(RunSpec(repo=root/'examples/tinybug/repo',issue=root/'examples/tinybug/issue.md',
    verification=root/'examples/tinybug/verification',output=root/'runs',demo=True,max_steps=1))
if first['status']!='step_limit':raise RuntimeError(first)
final=resume_task(first['output'],max_steps=5)
if not final['resolved'] or final['tool_calls']!=4 or final['model_responses']!=5:
    raise RuntimeError(final)
print({'run_id':final['run_id'],'resolved':final['resolved'],'tool_calls':final['tool_calls'],
       'model_responses':final['model_responses'],'resume_count':final['resume_count'],
       'evidence_type':'scripted','estimated_cost_rmb':final['estimated_cost_rmb']})

from pathlib import Path
import os
out=Path('output')
summary=os.environ.get('GITHUB_STEP_SUMMARY')
parts=[]
for name in ('BACKTEST_REPORT.md','CHECK_DATA.md','FAILURE.md'):
    p=out/name
    if p.exists():parts.append(p.read_text(encoding='utf-8'))
p=out/'telegram_preview.txt'
if p.exists():parts.append('```text\n'+p.read_text(encoding='utf-8')+'\n```')
if summary and parts:
    with open(summary,'a',encoding='utf-8') as f:f.write('\n\n'.join(parts))

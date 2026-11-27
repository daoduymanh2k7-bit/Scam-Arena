"""Read-only container startup diagnostics with configured credentials redacted."""
import json
import re
import subprocess

inspect=subprocess.run(['docker','inspect','scam-arena'],capture_output=True,text=True)
if inspect.returncode:
    print('Application container not available')
else:
    info=json.loads(inspect.stdout)[0]
    secret_values=[]
    for item in info.get('Config',{}).get('Env',[]):
        key,_,value=item.partition('=')
        if value and any(token in key.upper() for token in ('PASSWORD','API_KEY','TOKEN','SECRET','DATABASE_URL')):
            secret_values.append(value)
    def redact(text):
        for value in sorted(secret_values,key=len,reverse=True):text=text.replace(value,'[REDACTED]')
        return re.sub(r'sk-[A-Za-z0-9_-]+','[REDACTED]',text)
    state=info.get('State',{})
    print(json.dumps({key:state.get(key) for key in ['Status','OOMKilled','ExitCode','Error','StartedAt','FinishedAt']}))
    logs=subprocess.run(['docker','logs','--tail','80','scam-arena'],capture_output=True,text=True)
    print(redact(logs.stdout+logs.stderr))

"""Structured repository tools executed entirely inside the Docker sandbox."""
import json
import shlex

SHELL = {'type':'function','function':{'name':'shell','description':'Run a shell command in the isolated repository container. Use for tests and commands not covered by structured tools. No network; bounded output.',
    'parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command'],'additionalProperties':False}}}


def schema(name, description, properties, required):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{
        'type':'object','properties':properties,'required':required,'additionalProperties':False}}}


STRUCTURED = [
    schema('list_files','List repository files, excluding environment files, caches and Git internals.',
           {'path':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':200}},[]),
    schema('read_file','Read a bounded range of a UTF-8 source file with line numbers.',
           {'path':{'type':'string'},'start_line':{'type':'integer','minimum':1},'line_count':{'type':'integer','minimum':1,'maximum':200}},['path']),
    schema('search_text','Find a literal string in source files; returns paths and line numbers. Search is case-sensitive.',
           {'query':{'type':'string'},'path':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':100}},['query']),
    schema('replace_text','Replace an exact source fragment only when its occurrence count matches expected_count. Read the file first. Existing tests and configurations must remain unchanged.',
           {'path':{'type':'string'},'old':{'type':'string'},'new':{'type':'string'},'expected_count':{'type':'integer','minimum':1,'maximum':20}},['path','old','new']),
]

PROGRAM = r'''
import json,os,sys
from pathlib import Path
name,args=json.loads(sys.argv[1])
root=Path('/workspace').resolve()
def safe(value):
    relative=Path(value)
    if relative.is_absolute() or '..' in relative.parts or any(part=='.git' or part.startswith('.env') for part in relative.parts):
        raise ValueError('Path must stay inside the repository and exclude private metadata')
    resolved=(root/relative).resolve()
    if resolved!=root and root not in resolved.parents:
        raise ValueError('Path escapes repository')
    if any(part=='.git' or part.startswith('.env') for part in resolved.relative_to(root).parts):
        raise ValueError('Private metadata path is unsupported')
    if not resolved.exists(): raise FileNotFoundError('Repository path does not exist')
    return resolved
def files(path):
    count=0
    if path.is_file():
        yield path
        return
    for parent,dirs,names in os.walk(path,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in {'.git','.venv','__pycache__'} and not d.startswith('.env') and not (Path(parent)/d).is_symlink())
        for filename in sorted(names):
            file=Path(parent)/filename
            if file.is_symlink() or filename.startswith('.env'):
                continue
            yield file
            count+=1
            if count>=5000: return
def text(path):
    if path.stat().st_size>1_000_000:
        raise ValueError('File exceeds 1 MB limit')
    value=path.read_text()
    if '\0' in value: raise ValueError('Binary file is unsupported')
    return value
try:
    path=safe(args.get('path','.'))
    if name=='list_files':
        limit=args.get('limit',100)
        entries=[]
        for file in files(path):
            entries.append(str(file.relative_to(root)))
            if len(entries)>limit: break
        result={'files':entries[:limit],'truncated':len(entries)>limit}
    elif name=='read_file':
        lines=text(path).splitlines()
        start=args.get('start_line',1)-1
        count=args.get('line_count',100)
        result={'path':str(path.relative_to(root)),'total_lines':len(lines),
                'lines':[f'{index+1}: {lines[index]}' for index in range(start,min(len(lines),start+count))]}
    elif name=='search_text':
        query=args['query']
        if not query: raise ValueError('Query must not be empty')
        matches=[]
        limit=args.get('limit',50)
        for file in files(path):
            try: lines=text(file).splitlines()
            except (UnicodeError,OSError,ValueError): continue
            for index,line in enumerate(lines,1):
                if query in line:
                    matches.append({'path':str(file.relative_to(root)),'line':index,'text':line[:500]})
                    if len(matches)>=limit: break
            if len(matches)>=limit: break
        result={'matches':matches,'limit_reached':len(matches)>=limit}
    elif name=='replace_text':
        value=text(path)
        old=args['old']
        if not old: raise ValueError('Old text must not be empty')
        count=value.count(old)
        if count!=args.get('expected_count',1):
            raise ValueError(f'Expected occurrence count does not match actual count {count}; file unchanged')
        path.write_text(value.replace(old,args['new']))
        result={'path':str(path.relative_to(root)),'replacements':count}
    else: raise ValueError('Unknown structured tool')
    print(json.dumps(result,ensure_ascii=False))
except Exception as exc:
    print(json.dumps({'error':type(exc).__name__+': '+str(exc)}))
    sys.exit(1)
'''


class RepositoryTools:
    def __init__(self, runner, mode='shell'):
        if mode not in {'shell','structured'}:
            raise ValueError('Unsupported tool mode')
        self.runner=runner
        self.schemas=[SHELL] + (STRUCTURED if mode=='structured' else [])
        self.allowed={item['function']['name']:item['function']['parameters'] for item in self.schemas}

    def execute(self,name,args):
        if name not in self.allowed or not isinstance(args,dict):
            raise ValueError('Unknown tool or malformed arguments')
        specification=self.allowed[name]
        if set(args)-set(specification['properties']) or set(specification['required'])-set(args):
            raise ValueError('Unexpected or missing tool arguments')
        for key,value in args.items():
            field=specification['properties'][key]
            if field['type']=='string' and not isinstance(value,str):
                raise ValueError('Expected string: '+key)
            if field['type']=='integer' and (type(value) is not int or value<field.get('minimum',0) or value>field.get('maximum',10**9)):
                raise ValueError('Invalid integer: '+key)
        if name=='shell':
            return self.runner.run(args['command'])
        command='python -I -c '+shlex.quote(PROGRAM)+' '+shlex.quote(json.dumps([name,args],ensure_ascii=False))
        return self.runner.run(command)

"""Remove only obsolete SHA-named deployment packages; retain active/recent releases."""
import argparse
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

SHA=re.compile(r'^[0-9a-f]{40}$')
ARCHIVE=re.compile(r'^scam-arena-([0-9a-f]{40})[.]tar[.]gz$')


def within(path,parent):
    return path.resolve().is_relative_to(parent.resolve()) and path.resolve()!=parent.resolve()


def plan(archives,releases,active,keep=3,mounts=()):
    if not SHA.fullmatch(active):raise ValueError('Missing/invalid deployed revision; refusing cleanup')
    if keep<3:raise ValueError('Keep at least three releases')
    versions={}
    for parent,is_archive in [(archives,True),(releases,False)]:
        if not parent.exists():continue
        if parent.is_symlink():raise ValueError('Artifact root must not be a symlink')
        for path in parent.iterdir():
            match=ARCHIVE.fullmatch(path.name) if is_archive else SHA.fullmatch(path.name)
            if not match or path.is_symlink() or not within(path,parent):continue
            if (is_archive and not path.is_file()) or (not is_archive and not path.is_dir()):continue
            sha=match.group(1) if is_archive else path.name
            versions.setdefault(sha,[]).append(path)
    newest=sorted(versions,key=lambda sha:max(p.stat().st_mtime for p in versions[sha]),reverse=True)
    protected={active,*newest[:keep]}
    victims=[]
    for sha,paths in versions.items():
        if sha in protected:continue
        for path in paths:
            if any(path.resolve()==m.resolve() or path.resolve() in m.resolve().parents for m in mounts):continue
            # A source package should never contain runtime credentials.
            if path.is_dir() and any(path.rglob('.env')):continue
            victims.append(path)
    return sorted(victims),sorted(protected)


def size(path):
    if path.is_file():return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())


def remove(path,archives,releases):
    parent=archives if ARCHIVE.fullmatch(path.name) else releases
    if path.is_symlink() or not within(path,parent) or path.parent.resolve()!=parent.resolve():
        raise ValueError('Unsafe artifact path')
    if path.is_dir():
        if not SHA.fullmatch(path.name) or any(path.rglob('.env')):raise ValueError('Unsafe release directory')
        shutil.rmtree(path)
    elif path.is_file() and ARCHIVE.fullmatch(path.name):path.unlink()
    else:raise ValueError('Unexpected artifact type')


@contextmanager
def deployment_lock():
    import fcntl
    with open('/var/lock/scam-arena-deploy.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    archives=Path('/root');releases=Path('/opt/scam-arena-releases')
    with deployment_lock():
        active=Path('/opt/scam-arena/.deployed-revision').read_text().strip()
        ids=subprocess.check_output(['docker','ps','-aq'],text=True).split()
        mounts=[]
        if ids:
            containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
            mounts=[Path(m['Source']) for c in containers for m in c.get('Mounts',[]) if m.get('Source')]
        victims,protected=plan(archives,releases,active,mounts=mounts)
        before=shutil.disk_usage('/').free
        print(json.dumps({'active_revision':active,'retained_revisions':protected,'free_bytes_before':before}))
        total=0
        for path in victims:
            count=size(path);total+=count
            print(json.dumps({'action':'remove' if args.apply else 'would_remove','path':str(path),'bytes':count}),flush=True)
            if args.apply:remove(path,archives,releases)
        after=shutil.disk_usage('/').free
        print(json.dumps({'removed_artifacts':len(victims) if args.apply else 0,'artifact_bytes':total,'free_bytes_after':after,'reclaimed_bytes':after-before}))


if __name__=='__main__':main()

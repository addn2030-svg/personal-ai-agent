# -*- coding: utf-8 -*-
"""GitHub connector using a fine-grained PAT from the environment.

Read-only calls (recent_commits, open_prs, list_issues, get_file, doctor)
work with a read-only token. Write calls (create_issue, comment_issue,
close_issue, create_pull, merge_pull) need Issues/Pull requests/Contents
Read/Write on the PAT. No token value ever lives in this file or in chat —
only in the environment (GITHUB_TOKEN).
"""
from __future__ import annotations
import json, os, urllib.request, urllib.parse, urllib.error

TOKEN=os.environ.get('GITHUB_TOKEN','')
REPO=os.environ.get('AI_OS_GITHUB_REPO','addn2030-svg/personal-ai-agent')
API='https://api.github.com'


def _request(path,method='GET',payload=None):
    if not TOKEN: raise RuntimeError('GITHUB_TOKEN is not set')
    body=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(
        API+path,data=body,method=method,
        headers={'Authorization':f'Bearer {TOKEN}','Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Abdulrahman-AI-OS',
                 **({'Content-Type':'application/json'} if body else {})})
    return json.loads(urllib.request.urlopen(req,timeout=25).read())


def _get(path):
    return _request(path)


def _post(path,payload):
    return _request(path,method='POST',payload=payload)


def _patch(path,payload):
    return _request(path,method='PATCH',payload=payload)


def _fail(e):
    """GitHub HTTPError -> readable RuntimeError with the API message."""
    try:
        detail=json.loads(e.read()).get('message','')
    except Exception:
        detail=''
    return RuntimeError(f'GitHub API {e.code}: {detail or e.reason}')


def recent_commits(limit=20):
    rows=_get(f'/repos/{REPO}/commits?per_page={int(limit)}')
    return [{'sha':x['sha'],'message':x['commit']['message'],'date':x['commit']['committer']['date'],'url':x['html_url']} for x in rows]


def open_prs(limit=20):
    rows=_get(f'/repos/{REPO}/pulls?state=open&per_page={int(limit)}')
    return [{'number':x['number'],'title':x['title'],'updated_at':x['updated_at'],'draft':x.get('draft',False),'url':x['html_url']} for x in rows]


def list_issues(state='open',limit=20):
    rows=_get(f'/repos/{REPO}/issues?state={state}&per_page={int(limit)}')
    # GitHub folds PRs into the issues endpoint — drop them.
    return [{'number':x['number'],'title':x['title'],'state':x['state'],'url':x['html_url']}
            for x in rows if 'pull_request' not in x]


def get_file(path,ref=None):
    """File content at a repo-relative path, e.g. get_file('README.md')."""
    q=f'?ref={urllib.parse.quote(ref)}' if ref else ''
    meta=_get(f'/repos/{REPO}/contents/{urllib.parse.quote(path)}{q}')
    if meta.get('encoding')!='base64':
        raise RuntimeError(f'Not a file: {path}')
    import base64
    return base64.b64decode(meta['content']).decode('utf-8',errors='replace')


def doctor():
    repo=_get(f'/repos/{REPO}')
    return {'repo':repo.get('full_name'),'private':repo.get('private'),'default_branch':repo.get('default_branch')}


# -------------------------------------------------------------------- write --

def create_issue(title,body='',labels=()):
    try:
        row=_post(f'/repos/{REPO}/issues',{'title':title,'body':body,'labels':list(labels)})
    except urllib.error.HTTPError as e:
        raise _fail(e) from e
    return {'number':row['number'],'title':row['title'],'url':row['html_url']}


def comment_issue(number,body):
    try:
        row=_post(f'/repos/{REPO}/issues/{int(number)}/comments',{'body':body})
    except urllib.error.HTTPError as e:
        raise _fail(e) from e
    return {'id':row['id'],'url':row['html_url']}


def close_issue(number):
    try:
        row=_patch(f'/repos/{REPO}/issues/{int(number)}',{'state':'closed'})
    except urllib.error.HTTPError as e:
        raise _fail(e) from e
    return {'number':row['number'],'state':row['state'],'url':row['html_url']}


def create_pull(title,head,base='main',body=''):
    try:
        row=_post(f'/repos/{REPO}/pulls',{'title':title,'head':head,'base':base,'body':body})
    except urllib.error.HTTPError as e:
        raise _fail(e) from e
    return {'number':row['number'],'title':row['title'],'url':row['html_url']}


def merge_pull(number,merge_title=None):
    """Merge PR with the repo's default merge commit style."""
    try:
        req=urllib.request.Request(
            f'{API}/repos/{REPO}/pulls/{int(number)}/merge',
            data=json.dumps({'commit_title':merge_title} if merge_title else {}).encode(),
            method='PUT',
            headers={'Authorization':f'Bearer {TOKEN}','Accept':'application/vnd.github+json',
                     'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Abdulrahman-AI-OS',
                     'Content-Type':'application/json'})
        out=json.loads(urllib.request.urlopen(req,timeout=25).read())
    except urllib.error.HTTPError as e:
        raise _fail(e) from e
    return {'merged':out.get('merged',False),'sha':out.get('sha')}

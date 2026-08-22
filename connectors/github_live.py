# -*- coding: utf-8 -*-
"""Read-only GitHub connector using a fine-grained PAT from the environment."""
from __future__ import annotations
import json, os, urllib.request, urllib.parse

TOKEN=os.environ.get('GITHUB_TOKEN','')
REPO=os.environ.get('AI_OS_GITHUB_REPO','addn2030-svg/personal-ai-agent')
API='https://api.github.com'


def _get(path):
    if not TOKEN: raise RuntimeError('GITHUB_TOKEN is not set')
    req=urllib.request.Request(API+path,headers={'Authorization':f'Bearer {TOKEN}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'Abdulrahman-AI-OS'})
    return json.loads(urllib.request.urlopen(req,timeout=25).read())


def recent_commits(limit=20):
    rows=_get(f'/repos/{REPO}/commits?per_page={int(limit)}')
    return [{'sha':x['sha'],'message':x['commit']['message'],'date':x['commit']['committer']['date'],'url':x['html_url']} for x in rows]


def open_prs(limit=20):
    rows=_get(f'/repos/{REPO}/pulls?state=open&per_page={int(limit)}')
    return [{'number':x['number'],'title':x['title'],'updated_at':x['updated_at'],'draft':x.get('draft',False),'url':x['html_url']} for x in rows]


def doctor():
    repo=_get(f'/repos/{REPO}')
    return {'repo':repo.get('full_name'),'private':repo.get('private'),'default_branch':repo.get('default_branch')}

#!/usr/bin/env python

from os import environ
from os.path import isdir, join
from subprocess import run, PIPE, STDOUT, CalledProcessError
from sys import exit

def _run(cmd_string, **kwargs):
    cmd = cmd_string.split()
    cwd = repo_path if isdir(repo_path) else None

    return run(cmd, check=True, cwd=cwd, **kwargs)

repo_path = 'bot_repo_clone'

gh_token = environ['GITHUB_TOKEN']
gh_repo_name = environ['GITHUB_REPOSITORY']

branch_name = environ['BOT_BRANCH'] + '_' + environ['GITHUB_ACTION']
environment_path = environ['BOT_ENV_YML']
lock_path = environ['BOT_LOCKFILE']

assert not isdir(repo_path), repo_path
_run('git clone https://' + gh_token + '@github.com/' + gh_repo_name + '.git '
        + repo_path)
_run('git config user.name BOT')
_run('git config user.email <>')
_run('git checkout -b ' + branch_name)

_run('conda env remove -n bot_env')
_run('conda env create -n bot_env -f ' + environment_path)
new_lock = _run('conda list -n bot_env --explicit', encoding='utf-8',
        stderr=STDOUT, stdout=PIPE).stdout

# `open` isn't run from inside the `repo_path` like `_run` commands
with open(join(repo_path, lock_path), 'r+') as f:
    old_lock = f.read()
    if old_lock == new_lock:
        print('All packages are up to date')
        exit(2)
    else:
        print('Old lock was:')
        print(old_lock)
        f.seek(0)
        f.truncate()
        f.write(new_lock)
        f.seek(0)
        print('New lock is:')
        print(f.read())

_run('git commit -m LOCK_BUMP ' + lock_path)
_run('git push -u origin ' + branch_name)

_run('git config --unset user.name')
_run('git config --unset user.email')

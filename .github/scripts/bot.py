#!/usr/bin/env python

from os import environ
from os.path import isdir, join
from subprocess import run, PIPE, STDOUT, CalledProcessError
from sys import exit

from github import Github

def _run(cmd_string, **kwargs):
    cmd = cmd_string.split()
    cwd = repo_path if isdir(repo_path) else None

    return run(cmd, check=True, cwd=cwd, **kwargs)

def _get_env(env_name):
    env_var = environ[env_name]
    print('* ' + env_name + ': ' + env_var)
    return env_var

repo_path = 'bot_repo_clone'

print('Environment variables used are:')
# Correct token will be replaced by asterisks in GH Actions log
gh_token = _get_env('GITHUB_TOKEN')
gh_repo_name = _get_env('GITHUB_REPOSITORY')

branch_name = _get_env('BOT_BRANCH') + '_' + _get_env('GITHUB_RUN_ID')
environment_path = _get_env('BOT_ENV_YML')
lock_path = _get_env('BOT_LOCKFILE')
pr_base_branch_name = _get_env('BOT_PR_BASE')
print()

assert not isdir(repo_path), repo_path
# Only the `gh_token` matters but without any username it doesn't always work
_run('git clone https://username:' + gh_token + '@github.com/' + gh_repo_name
        + '.git ' + repo_path)
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

gh_repo = Github(gh_token).get_repo(gh_repo_name)
# It's necessary to pass 4 arguments so the body can't be skipped
gh_repo.create_pull(head=branch_name, base=pr_base_branch_name,
        title='[BOT] Bump ' + lock_path, body='')

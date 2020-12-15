#!/usr/bin/env python

from os import environ, chdir
from os.path import isdir, join, exists, dirname
from subprocess import run, PIPE
from sys import exit
from re import match, search, VERBOSE

from github import Github

def _run(cmd_string, return_stdout=False, **kwargs):
    cmd = cmd_string.split()

    if return_stdout:
        return run(cmd, check=True, encoding='utf-8', stdout=PIPE,
                **kwargs).stdout
    else:
        return run(cmd, check=True, **kwargs)

def _get_env(env_name):
    env_var = environ[env_name]
    print('* ' + env_name + ': ' + env_var)
    return env_var

conda_env = 'bot_env'

print('Environment variables used are:')
# The actual token will be replaced by asterisks in GH Actions log
gh_token = _get_env('GITHUB_TOKEN')
gh_repo_name = _get_env('GITHUB_REPOSITORY')

branch_name = _get_env('BOT_BRANCH') + '_' + _get_env('GITHUB_RUN_ID')
environment_path = _get_env('BOT_ENV_YML')
conda_lock_path = _get_env('BOT_CONDA_LOCK')
pip_lock_path = _get_env('BOT_PIP_LOCK')
pr_base_branch_name = _get_env('BOT_PR_BASE')
print()


_run('git config user.name BOT')
_run('git config user.email <>')
_run('git checkout -b ' + branch_name)

_run('conda env remove -n ' + conda_env)
_run('conda env create -n ' + conda_env + ' -f ' + environment_path)

# Capture explicit list of Conda packages
conda_lock = _run('conda list --explicit -n ' + conda_env, return_stdout=True)

# Capture frozen list of pip packages

# It will stay None in case there's no pip in environment.yml
pip_lock = None

# Check pip version
pip_version_match = search(r'pip\-([0-9]+)\.([0-9]+)[^\-]+-[^\-]+\.conda',
        conda_lock, VERBOSE)
if pip_version_match is not None:
    major, minor = pip_version_match.groups()
    if int(major) < 20 or ( int(major) == 20 and int(minor) == 0 ):
        print('WARNING: The current version of pip (older than 20.1) is unable'
                + ' to properly handle git-based packages!')

    pip_lock = ''
    print()
    for pip_spec in _run('conda run -n ' + conda_env + ' python -m pip freeze',
            return_stdout=True).split('\n'):
        # Remove packages installed by Conda (lines: 'NAME @ file://PATH/work')
        conda_pkg_match = match(r'(\S+) @ file://.*/work.*', pip_spec)
        if conda_pkg_match is None:
            pip_lock += pip_spec + '\n'
        else:
            print('Conda package removed from pip.lock: ' + conda_pkg_match.group(1))
    print()

# Returns True if lock file has been updated, False otherwise
def try_updating_lock_file(path, new_lock):
    try:
        with open(path, 'r') as f:
            old_lock = f.read()
            if old_lock == new_lock:
                print(path + ' is up to date')
                print()
                return False
    except FileNotFoundError:
        print(path + ' doesn\'t exist; it will be created')
        print()
    with open(path, 'w') as f:
        f.write(new_lock)
    return True

updated_files = []
if try_updating_lock_file(conda_lock_path, conda_lock):
    updated_files.append(conda_lock_path)
if pip_lock and try_updating_lock_file(pip_lock_path, pip_lock):
    updated_files.append(pip_lock_path)

# Commiting without any change will cause error
if len(updated_files) > 0:
    _run('git add ' + ' '.join(updated_files))
    _run('git commit -m LOCK_BUMP ')
    _run('git push -u origin ' + branch_name)

    gh_repo = Github(gh_token).get_repo(gh_repo_name)
    # It's necessary to pass 4 arguments so the body can't be skipped
    gh_repo.create_pull(head=branch_name, base=pr_base_branch_name,
            title='[BOT] Bump ' + ' and '.join(updated_files), body='')
else:
    print('Both locks are up to date!')

# TODO remove?
_run('git config --unset user.name')
_run('git config --unset user.email')

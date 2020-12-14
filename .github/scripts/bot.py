#!/usr/bin/env python

from os import environ, chdir
from os.path import isdir, join, exists, dirname
from subprocess import run, PIPE, CalledProcessError
from sys import exit
from re import match, search, VERBOSE

# Conda's `pip` doesn't install `ruamel.yaml` because it finds it is already
# installed but the one from Conda has to be imported with `ruamel_yaml`
try:
    from ruamel.yaml import YAML
except ModuleNotFoundError:
    from ruamel_yaml import YAML
yaml = YAML()
yaml.allow_duplicate_keys = True

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
repo_path = 'bot_repo_clone'

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

assert not isdir(repo_path), repo_path
# Only the `gh_token` matters but without any username it doesn't always work
_run('git clone https://username:' + gh_token + '@github.com/' + gh_repo_name
        + '.git ' + repo_path)
# Work in the cloned repository from now on
chdir(repo_path)

_run('git config user.name BOT')
_run('git config user.email <>')
_run('git checkout -b ' + branch_name)

# Manage pip requirements
def get_github_specification(specification):
    match = search(r'''
        (github.com/[^@\#\s]*)    # address without protocol
        @?([^\#\s]*)?             # optional @REVISION without @
        \#?([^\s]*)?                # optional #EGG without #
        ''', specification, VERBOSE)
    if match == None:
        return None
    else:
        gh_spec = {
            'address':  match.group(1),
            'name':     match.group(1).split('/')[-1].rstrip('.git'),
            'revision': match.group(2) or 'HEAD',
            'egg':      match.group(3),
            }
        return gh_spec

# Return untouched if None, extend if appending a list and append otherwise
def append_flat_if_not_none(appended_list, unknown_type_element):
    if unknown_type_element is not None:
        if isinstance(unknown_type_element, list):
            appended_list.extend(unknown_type_element)
        else:
            appended_list.append(unknown_type_element)
    return appended_list

def analyze_pip_requirement(requirement):
    path_match = match(r'-r (file:)?(.*)', requirement)
    if path_match is None:
        return get_github_specification(requirement)
    else:  # `requirement` includes some additional `requirements.txt` file
        # `-r PATH` is relative to the environment file
        req_path = join(dirname(environment_path), path_match.group(2))
        print('Found additional pip requirements file: ' + req_path)
        with open(req_path, 'r') as f:
            file_git_repos_found = []
            for req_line in f.readlines():
                git_repos_found = analyze_pip_requirement(req_line)
                file_git_repos_found = append_flat_if_not_none(
                    file_git_repos_found, git_repos_found )
            return file_git_repos_found

with open(environment_path, 'r') as f:
    env_yml = yaml.load(f.read())

all_git_specs = []
for dependency in env_yml['dependencies']:
    if isinstance(dependency, dict) and 'pip' in dependency.keys():
        for pip_requirement in dependency['pip']:
            dependency_git_specs = analyze_pip_requirement(pip_requirement)
            # There might be more than one git spec returned if it's `-r PATH`
            all_git_specs = append_flat_if_not_none(all_git_specs,
                    dependency_git_specs)
print()
print('Git specs found:')
for specs in all_git_specs:
    print(specs)
print()
#exit(0)

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

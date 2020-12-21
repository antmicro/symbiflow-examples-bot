#!/usr/bin/env python

from os import environ
from subprocess import run, DEVNULL, PIPE
from sys import exit
from re import match, search

from ruamel.yaml import YAML
yaml = YAML()
yaml.allow_duplicate_keys = True

def _run(cmd_string, multiword_last_arg='', return_stdout=False, **kwargs):
    cmd = cmd_string.split() + ([multiword_last_arg]
            if multiword_last_arg else [])
    if return_stdout:
        return run(cmd, check=True, encoding='utf-8', stdout=PIPE,
                **kwargs).stdout
    else:
        return run(cmd, check=True, **kwargs)

def _get_env(env_name, required=True):
    if env_name not in environ:
        if required:
            print('ERROR: Required environment variable not found: ' + env_name + '!')
        return None
    env_var = environ[env_name]
    print('* ' + env_name + ': ' + env_var)
    return env_var

def _remove_conda_env(conda_env_name):
    print('Removing `' + conda_env_name + '` Conda environment... ', end='')
    _run('conda env remove -n ' + conda_env_name, stdout=DEVNULL,
            stderr=DEVNULL)
    print('done!')
    print()

# Returns True if lock file has been updated, False otherwise
def try_updating_lock_file(path, new_lock):
    print('Trying to update `' + path + '`...')
    try:
        with open(path, 'r') as f:
            old_lock = f.read()
            if old_lock == new_lock:
                print(path + ' is up to date.')
                print()
                return False
    except FileNotFoundError:
        print(path + ' doesn\'t exist; it will be created.')
    with open(path, 'w') as f:
        f.write(new_lock)
    print()
    return True

def separate_and_save_deps(env_yml_path):
    with open(env_yml_path, 'r') as f:
        env_yml = yaml.load(f.read())
    for dependency in env_yml['dependencies']:
        # `- pip:` line becomes a dict-like object with `pip` key after parsing
        if isinstance(dependency, dict) and 'pip' in dependency.keys():
            # `pip:` key is replaced with `pip` package to have it installed
            # even when there was only `pip:` key in `environment.yml`
            env_yml['dependencies'].remove(dependency)
            env_yml['dependencies'].append('pip')

            # Save `environment.yml` without pip requirements
            pipless_env_yml_path = 'bot-env.yml'
            with open(pipless_env_yml_path, 'w') as f:
                yaml.dump(env_yml, f)

            # Save extracted requirements
            pip_req_path = 'bot-req.txt'
            with open(pip_req_path, 'w') as f:
                f.writelines(list(dependency['pip']))

            return (pipless_env_yml_path, pip_req_path)
    return (env_yml_path, None)

def main():
    print('Environment variables used are:')
    conda_env = _get_env('BOT_ENV_NAME')
    env_yml_path = _get_env('BOT_ENV_YML')
    conda_lock_path = _get_env('BOT_CONDA_LOCK')
    pip_lock_path = _get_env('BOT_PIP_LOCK', required=False)
    print()
    if None in [conda_env, env_yml_path, conda_lock_path]:
        exit(1)

    (pipless_env_yml_path, pip_req_path) = separate_and_save_deps(env_yml_path)
    if pip_req_path and pip_lock_path is None:
            print('ERROR: Conda environment from `' + env_yml_path +
                    '` depends on pip packages!')
            print('Please set BOT_PIP_LOCK environment variable and rerun.')
            print()
            exit(1)

    print('Creating `' + conda_env + '` environment based on `'
            + pipless_env_yml_path + '`...')
    print()
    try:
        _run('conda env create -n ' + conda_env + ' -f ' + pipless_env_yml_path)
    except:
        print('ERROR: Creating `' + conda_env + '` environment failed!')
        print('Please remove any environment with such name, if exists.')
        print()
        exit(1)

    if pip_req_path:
        # `--live-stream` avoids buffering output by `conda run`
        pip_cmd = 'conda run --live-stream -n ' + conda_env + ' python -I -m pip '

        _run(pip_cmd + 'install -r ' + pip_req_path)
        pip_lock = _run(pip_cmd + 'freeze', return_stdout=True)
        print()
        print('Locked:')
        print()
        print(pip_lock)
    exit()

    # Capture explicit list of Conda packages
    conda_lock = _run('conda list -n ' + conda_env, return_stdout=True)
    print('Conda packages captured.')
    print()

    # Capture frozen list of pip packages

    # Variable will stay None in case there's no pip in environment.yml
    pip_lock = None

    # Check pip version
    pip_version_match = search(r'pip\-([0-9]+)\.([0-9]+)[^\-]+-[^\-]+\.',
            conda_lock)
    if pip_version_match is not None:
        if pip_lock_path is None:
            print('ERROR: The environment uses pip dependencies but '
                    + 'BOT_PIP_LOCK environment variable hasn\'t been set!')
            print()
            _remove_conda_env(conda_env)
            exit(1)

        major, minor = pip_version_match.groups()
        if int(major) < 20 or ( int(major) == 20 and int(minor) == 0 ):
            print('WARNING: The current version of pip (older than 20.1) is unable'
                    + ' to properly handle git-based packages!')
            print()

        pip_lock = ''
        for pip_spec in _run('conda run -n ' + conda_env + ' python -m pip freeze',
                return_stdout=True).split('\n'):
            # Remove packages installed by Conda (lines: 'NAME @ file://PATH/work')
            conda_pkg_match = match(r'(\S+) @ file://.*/work.*', pip_spec)
            if conda_pkg_match is None:
                pip_lock += pip_spec + '\n'
            else:
                print('Conda package removed from pip.lock: ' + conda_pkg_match.group(1))
        print()
        print('Pip packages captured.')
        print()

    # Conda environment isn't needed anymore
    _remove_conda_env(conda_env)
    updated_files = []

    if try_updating_lock_file(conda_lock_path, conda_lock):
        updated_files.append(conda_lock_path)
    if pip_lock and try_updating_lock_file(pip_lock_path, pip_lock):
        updated_files.append(pip_lock_path)

    if len(updated_files) == 0:
        print('Both locks are up to date!')
        exit(3)
    else:
        print('Locks successfully updated:')
        for file in updated_files:
            print('* ' + file)
        exit(0)

if __name__ == '__main__':
    main()

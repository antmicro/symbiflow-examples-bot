#!/usr/bin/env python

from io import StringIO
from os import environ
from os.path import dirname, exists, isdir, join, splitext
from subprocess import run, DEVNULL, PIPE, CalledProcessError
from sys import exit
from re import match, search, sub
from tempfile import NamedTemporaryFile

from ruamel.yaml import YAML
yaml = YAML()
yaml.allow_duplicate_keys = True

def _run(cmd_string, multiword_last_arg='', return_stdout=False, **kwargs):
    cmd = cmd_string.split() + ([multiword_last_arg]
            if multiword_last_arg else [])
    if return_stdout:
        try:
            return run(cmd, check=True, encoding='utf-8', stdout=PIPE,
                    **kwargs).stdout
        except CalledProcessError as e:
            print(e.output)
            raise
    else:
        return run(cmd, check=True, **kwargs)

def _get_env(env_name):
    if env_name not in environ:
        print('ERROR: Required environment variable not found: ' + env_name + '!')
        return None
    env_var = environ[env_name]
    print('* ' + env_name + ': ' + env_var)
    return env_var

# Returns True if lock file has been updated, False otherwise
def try_updating_lock_file(path, lock_yml):
    print('Trying to update `' + path + '`...')
    with StringIO() as tmp_stream:
        yaml.dump(lock_yml, tmp_stream)
        new_lock = tmp_stream.getvalue()
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
    print(path + ' has been updated successfully!')
    print()
    return True

def analyze_pip_requirement(requirement, analyzed_file_dir):
    path_match = match(r'-r (file:)?(.*)', requirement)
    if path_match is None:
        return [ requirement ]
    else:  # `requirement` includes some additional `requirements.txt` file
        # `-r PATH` is relative to the environment file
        req_path = join(analyzed_file_dir, path_match.group(2))
        print('Found additional pip requirements file: ' + req_path)
        with open(req_path, 'r') as f:
            file_requirements = []
            for req_line in f.readlines():
                file_requirements.extend(
                        analyze_pip_requirement(req_line, dirname(req_path))
                )
            return file_requirements

def get_all_pip_dependencies(pip_dependencies, analyzed_file_dir):
    all_pip_dependencies = []
    for pip_dependency in pip_dependencies:
        all_pip_dependencies.extend(
                analyze_pip_requirement(pip_dependency, analyzed_file_dir)
        )
    return all_pip_dependencies

def extract_pip_dependencies(env_yml_path):
    with open(env_yml_path, 'r') as f:
        env_yml = yaml.load(f.read())

    pip_dependencies = None
    for dependency in env_yml['dependencies']:
        # `- pip:` line becomes a dict-like object with `pip` key after parsing
        if isinstance(dependency, dict) and 'pip' in dependency.keys():
            # `pip:` key is replaced with `pip` package to have it installed
            # even when there was only `pip:` key in `environment.yml`
            env_yml['dependencies'].remove(dependency)
            env_yml['dependencies'].append('pip')
            env_yml_pip_dependencies = list(dependency['pip'])

            # Save `environment.yml` without pip requirements
            env_yml_path = 'bot-env.yml'
            with open(env_yml_path, 'w') as f:
                yaml.dump(env_yml, f)
    return (env_yml['name'], env_yml_path, env_yml_pip_dependencies)


def get_local_pip_dependencies(pip_dependencies, root_dir):
    local_pip_dependencies = []
    local_pip_deps_names = []
    for dependency in pip_dependencies:
        dependency = dependency.strip()
        # Handle comments
        if dependency.startswith('#'):
            continue
        only_dependency = sub(r'(.*)\s+#.*$', r'\1', dependency)

        # Find core of the dependency line without version etc.
        core_match = search(r'(^|\s)([^\s-][^\s=<>~!;]+)', only_dependency)
        if core_match is not None:
            dependency_path = join(root_dir, core_match.group(2))
            if isdir(dependency_path):
                setup_path = join(dependency_path, 'setup.py')
                if exists(setup_path):
                    dependency_name = _run('python setup.py --name',
                            cwd=dependency_path, return_stdout=True).strip()
                    local_pip_deps_names.append(dependency_name)
                    local_pip_dependencies.append(dependency)
    return (local_pip_dependencies, local_pip_deps_names)


class CondaEnvironmentContext:
    def __init__(self, name, env_path):
        self._name = name
        self._env_path = env_path

    def __enter__(self):
        print('Creating `' + self._name + '` environment based on `'
                + self._env_path + '`...')
        print()
        try:
            _run('conda env create -n ' + self._name + ' -f ' + self._env_path)
        except:
            print('ERROR: Creating `' + self._name + '` environment failed!')
            print('Please remove any environment with such name, if exists.')
            print()
            exit(1)

    def __exit__(self, exc_type, exc_value, traceback):
        print('Removing `' + self._name + '` Conda environment... ', end='')
        _run('conda env remove -n ' + self._name, stdout=DEVNULL,
                stderr=DEVNULL)
        print('done!')
        print()


def main():
    print('Environment variables used are:')
    env_yml_path = _get_env('BOT_ENV_YML')
    conda_lock_path = _get_env('BOT_CONDA_LOCK')
    print()
    if None in [env_yml_path, conda_lock_path]:
        exit(1)

    # Conda only supports creating environments from .txt/.yml/.yaml files
    _, conda_lock_ext = splitext(conda_lock_path)
    if conda_lock_ext not in ['.txt', '.yml', '.yaml']:
        print('ERROR: Invalid conda lock extension (`' + conda_lock_ext
                + '`); it must be `.txt`, `.yml` or `.yaml`!')
        exit(1)

    (conda_env, pipless_env_yml_path, env_yml_pip_deps) = extract_pip_dependencies(
            env_yml_path)

    with CondaEnvironmentContext(conda_env, pipless_env_yml_path):
        conda_lock = _run('conda run -n ' + conda_env + ' conda env export',
                return_stdout=True)
        conda_lock_yaml = yaml.load(conda_lock)
        print('Conda packages captured.')
        print()

        # Lock pip dependencies
        if env_yml_pip_deps:
            pip_cmd = 'conda run --no-capture-output -n ' + conda_env + ' python -I -m pip '
            all_pip_deps = get_all_pip_dependencies(env_yml_pip_deps,
                dirname(env_yml_path))

            # Local pip dependencies will be uninstalled and copied in the original
            # form as freezing breaks them (git handles their versioning after all).
            (local_deps, local_deps_names) = get_local_pip_dependencies(
                    all_pip_deps, dirname(env_yml_path))

            print('Installing pip dependencies...')
            print()
            with NamedTemporaryFile('w+', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(env_yml_pip_deps))
                f.flush()

                # Possible requirements file paths are relative to `environment.yml`
                env_yml_dir = dirname(env_yml_path)
                _run(pip_cmd + 'install -r ' + f.name, cwd=env_yml_dir or '.')
            print()

            # Uninstall local packages
            if local_deps and local_deps_names:
                print('Uninstalling local pip packages (they were installed '
                        + 'only to lock their dependencies\' versions)...')
                print()
                for local_pkg in local_deps_names:
                    _run(pip_cmd + 'uninstall --yes ' + local_pkg)
                print()

            pip_locked_pkgs = []
            for pip_spec in _run(pip_cmd + 'freeze', return_stdout=True).splitlines():
                if pip_spec:
                    # Ignore pip packages installed by Conda
                    # (lines: 'NAME @ file://PATH/work')
                    conda_pkg_match = match(r'(\S+) @ file://.*/work.*', pip_spec)
                    if conda_pkg_match is not None:
                        print('Ignoring pip package installed by Conda: '
                                + conda_pkg_match.group(1))
                        continue
                    pip_locked_pkgs.append(pip_spec)

            # Add local packages
            if local_deps:
                pip_locked_pkgs.extend(local_deps)

            # Add locked pip packages to the `conda env export` yaml output
            if pip_locked_pkgs:
                conda_lock_yaml['dependencies'].append({'pip': pip_locked_pkgs})

            print()
            print('Pip packages captured.')
            print()

    # Apply yaml offset used by `conda env export`
    yaml.indent(offset=2)
    if not try_updating_lock_file(conda_lock_path, conda_lock_yaml):
        exit(3)

if __name__ == '__main__':
    main()

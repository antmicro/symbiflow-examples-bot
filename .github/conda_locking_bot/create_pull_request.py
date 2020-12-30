#!/usr/bin/env python3

import json
import requests
import sys
from os import environ


def create_pull_request(gh_repo, gh_token, pr_base, pr_head, pr_title):
    response = requests.post(
            'https://api.github.com/repos/' + gh_repo + '/pulls',
            headers={
                'Authorization': 'token ' + gh_token,
                'Accept': 'application/vnd.github.v3+json',
                },
            json={
                'base':  pr_base,
                'head':  pr_head,
                'title': pr_title,
                },
            )
    if response.status_code != 201:
        print('ERROR: Pull Request creation failed with status: '
                + str(response.status_code) + ' ' + response.reason)
        print()
        print('GitHub API response data was:')
        json.dump(response.json(), sys.stdout, indent=2)
        print()
        sys.exit(1)
    else:
        print('Pull Request created successfully!')
        print('It\'s available at: ' + response.json()['html_url'])


if __name__ == '__main__':
    create_pull_request(
            environ['GITHUB_REPOSITORY'],
            environ['GITHUB_TOKEN'],
            environ['PR_BASE'],
            environ['PR_HEAD'],
            environ['PR_TITLE'],
            )

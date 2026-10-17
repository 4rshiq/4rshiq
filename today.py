"""
Updates light_mode.svg and dark_mode.svg with live GitHub stats.

Structure and approach adapted from Andrew6rant's today.py
(https://github.com/Andrew6rant/Andrew6rant). Trimmed down: no deleted-repo archive.

Needs two environment variables (set by the GitHub Actions workflow):
    ACCESS_TOKEN  - a personal access token (stored as a repo secret, never in a file)
    USER_NAME     - your GitHub username
"""
import datetime
import hashlib
import os
import time

import requests
from dateutil import relativedelta
from lxml import etree

from align import WIDTH as INFO_WIDTH

API_URL = 'https://api.github.com/graphql'
HEADERS = {'Authorization': 'bearer ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']

BIRTHDAY = datetime.datetime(2007, 7, 16)  # used for the Uptime line

AFFILIATIONS = ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER']
SVG_FILES = ['light_mode.svg', 'dark_mode.svg']

CACHE_DIR = 'cache'
CACHE_FILE = os.path.join(CACHE_DIR, hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt')
CACHE_HEADER = [
    '# Cache of repositories I own or contribute to (names are hashed).\n',
    '# columns: repo_hash  total_commits  my_commits  loc_added_by_me  loc_deleted_by_me\n',
]

# Width of the info column comes from align.py (change WIDTH there, then run align.py).
# Each stat row is ". " + label + ":" + <dots + value>, so the dots+value area is what is left.
STAT_LABELS = {
    'age_data': 'Uptime',
    'repo_data': 'Repos',
    'contrib_data': 'Contributed',
    'star_data': 'Stars',
    'commit_data': 'Commits',
    'follower_data': 'Followers',
    'loc_data': 'Lines.Total',
    'loc_add': 'Lines.Added',
    'loc_del': 'Lines.Deleted',
}
FIELD_WIDTH = {key: INFO_WIDTH - (2 + len(label) + 1) for key, label in STAT_LABELS.items()}


# --------------------------------------------------------------------- uptime

def format_plural(unit):
    return 's' if unit != 1 else ''


def daily_readme(birthday):
    """Time since birth, e.g. '19 years, 3 months, 1 day'."""
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} year{}, {} month{}, {} day{}'.format(
        diff.years, format_plural(diff.years),
        diff.months, format_plural(diff.months),
        diff.days, format_plural(diff.days))


# ---------------------------------------------------------------- GitHub API

def run_query(query, variables, retries=3):
    """POST a GraphQL query, retrying on temporary server errors."""
    for attempt in range(retries):
        response = requests.post(API_URL, json={'query': query, 'variables': variables},
                                 headers=HEADERS, timeout=60)
        if response.status_code == 200:
            body = response.json()
            if body.get('data') is None:
                raise RuntimeError(body.get('errors'))
            return body['data']
        if response.status_code in (502, 503, 504) and attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f'GitHub API returned {response.status_code}: {response.text[:300]}')


def get_user():
    """Returns (account id, follower count)."""
    data = run_query(
        'query($login: String!) { user(login: $login) { id followers { totalCount } } }',
        {'login': USER_NAME})
    return data['user']['id'], data['user']['followers']['totalCount']


def get_owned_totals():
    """Returns (number of repos I own, total stars on them)."""
    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                nodes { stargazerCount }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    repos, stars, cursor = 0, 0, None
    while True:
        page = run_query(query, {'login': USER_NAME, 'cursor': cursor})['user']['repositories']
        repos = page['totalCount']
        stars += sum(node['stargazerCount'] for node in page['nodes'])
        if not page['pageInfo']['hasNextPage']:
            return repos, stars
        cursor = page['pageInfo']['endCursor']


def list_repos():
    """Returns [(owner/name, total commits on default branch)] for every repo I own or contribute to.
    60 per page on purpose: bigger pages tend to time out (502)."""
    query = '''
    query($login: String!, $cursor: String, $aff: [RepositoryAffiliation]) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $aff) {
                nodes {
                    nameWithOwner
                    defaultBranchRef { target { ... on Commit { history { totalCount } } } }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    repos, cursor = [], None
    while True:
        page = run_query(query, {'login': USER_NAME, 'cursor': cursor, 'aff': AFFILIATIONS})['user']['repositories']
        for node in page['nodes']:
            ref = node['defaultBranchRef']
            total = ref['target']['history']['totalCount'] if ref else 0  # empty repo -> no branch
            repos.append((node['nameWithOwner'], total))
        if not page['pageInfo']['hasNextPage']:
            return repos
        cursor = page['pageInfo']['endCursor']


def count_my_commits(owner, name, user_id):
    """Walks one repo's history (100 commits per request) and sums only MY commits.
    Returns (my_commits, lines_added, lines_deleted)."""
    query = '''
    query($owner: String!, $name: String!, $cursor: String) {
        repository(owner: $owner, name: $name) {
            defaultBranchRef { target { ... on Commit {
                history(first: 100, after: $cursor) {
                    nodes { additions deletions author { user { id } } }
                    pageInfo { endCursor hasNextPage }
                }
            } } }
        }
    }'''
    mine = added = deleted = 0
    cursor = None
    while True:
        repo = run_query(query, {'owner': owner, 'name': name, 'cursor': cursor})['repository']
        ref = repo['defaultBranchRef'] if repo else None
        if not ref:
            break
        history = ref['target']['history']
        for commit in history['nodes']:
            author = (commit['author'] or {}).get('user')
            if author and author['id'] == user_id:
                mine += 1
                added += commit['additions']
                deleted += commit['deletions']
        if not history['pageInfo']['hasNextPage']:
            break
        cursor = history['pageInfo']['endCursor']
    return mine, added, deleted


# --------------------------------------------------------------------- cache

def load_cache():
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                repo_hash, total, mine, added, deleted = line.split()
                cache[repo_hash] = [int(total), int(mine), int(added), int(deleted)]
    return cache


def save_cache(cache):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        f.writelines(CACHE_HEADER)
        for repo_hash, (total, mine, added, deleted) in cache.items():
            f.write(f'{repo_hash} {total} {mine} {added} {deleted}\n')


def collect_totals(user_id):
    """Only re-reads a repo's history if its commit count changed since the last run."""
    old = load_cache()
    new = {}
    repos = list_repos()
    try:
        for name, total in repos:
            repo_hash = hashlib.sha256(name.encode('utf-8')).hexdigest()
            if repo_hash in old and old[repo_hash][0] == total:
                new[repo_hash] = old[repo_hash]
                continue
            owner, repo_name = name.split('/')
            mine, added, deleted = count_my_commits(owner, repo_name, user_id)
            new[repo_hash] = [total, mine, added, deleted]
    except Exception:
        save_cache({**old, **new})  # keep the progress so the next run resumes
        raise
    save_cache(new)
    commits = sum(v[1] for v in new.values())
    added = sum(v[2] for v in new.values())
    deleted = sum(v[3] for v in new.values())
    return len(repos), commits, added, deleted


# ----------------------------------------------------------------------- SVG

def dots_for(width, text):
    """Dotted leader that makes (dots + value) exactly `width` characters wide."""
    k = width - len(text)
    if k <= 0:
        return ''
    if k == 1:
        return ' '
    if k == 2:
        return '. '
    return ' ' + '.' * (k - 2) + ' '


def update_svg(path, values):
    tree = etree.parse(path)
    root = tree.getroot()
    for element_id, value in values.items():
        text = f'{value:,}' if isinstance(value, int) else str(value)
        element = root.find(f".//*[@id='{element_id}']")
        if element is None:
            continue
        element.text = text
        dots = root.find(f".//*[@id='{element_id}_dots']")
        if dots is not None:
            dots.text = dots_for(FIELD_WIDTH[element_id], text)
    tree.write(path, encoding='utf-8', xml_declaration=True)


# ---------------------------------------------------------------------- main

if __name__ == '__main__':
    user_id, followers = get_user()
    owned_repos, stars = get_owned_totals()
    contributed_repos, commits, added, deleted = collect_totals(user_id)

    values = {
        'age_data': daily_readme(BIRTHDAY),
        'repo_data': owned_repos,
        'contrib_data': contributed_repos,
        'star_data': stars,
        'commit_data': commits,
        'follower_data': followers,
        'loc_data': added - deleted,
        'loc_add': added,
        'loc_del': deleted,
    }
    for svg in SVG_FILES:
        update_svg(svg, values)
    print(values)

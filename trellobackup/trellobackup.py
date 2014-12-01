#! /usr/bin/python
# -*- coding: utf8 -*-
"""
trellobackup.py
===============

Playing around with the Trello API in order to backup all boards.

Using the py-trello (https://github.com/sarumont/py-trello) client library to
retrieve our trello data.
Docs are missing (only very succint README), but the code is quite clear and
easy to read.

What's left (high level):
-------------------------

    - Check that we have all the data we need.
    - Better external config management (error checking, defaults...)

Miscellanous notes:
-------------------

    - python2.7 because py-trello depends on oauth2, which doesn't support
      py3 yet.

Ideas:
------

    - Accept a command line param to retrieve only a specific board ?
      not that useful if we only let the script run automagically via cron,
      but would be handy for testing...

"""
import os
import logging
import contextlib
import subprocess
from ConfigParser import ConfigParser
from datetime import datetime

import yaml
import trello

# TODO: Externalize this template (and reference it in conf)?
TXT_DUMP_TEMPLATE = u"""{card[name]}

{card[description]}

Comments:
{comments}
"""
TXT_DUMP_COMMENTS_TEMPLATE = u"""{comment[memberCreator][username]}
{comment[date]}

{comment[data][text]}
"""

# --- CONFIG ---

CONF_READER = ConfigParser()
CONF_READER.read(['trellobackuprc'])

API_KEY = CONF_READER.get('trello api', 'API_KEY')
API_SECRET = CONF_READER.get('trello api', 'API_SECRET')
TOKEN = CONF_READER.get('trello api', 'TOKEN')

RESULTS_DIR_ROOT = CONF_READER.get('local config', 'RESULTS_DIR_ROOT')
# from conf or not ?
BLOBS_ROOT = os.path.abspath(os.path.join(RESULTS_DIR_ROOT, 'raw_tickets'))
TREE_ROOT = os.path.abspath(os.path.join(RESULTS_DIR_ROOT, 'current'))

GIT_REPO_URL = CONF_READER.get('local config', 'GIT_REPO_URL')

# --- LOGGER config ---

logging.basicConfig()
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

# --- Utils ---

@contextlib.contextmanager
def temporary_chdir(path):
    """
    Change working directory to `path`, and goes back to the previous cwd
    when exiting the context block.

    """
    old_dir = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_dir)


def toyaml(data):
    """ Convert a `data` dictionary to a yaml string. """
    return yaml.safe_dump(data, allow_unicode=True, encoding='utf-8')


def normpath(*fragments):
    """
    Normalize path, replacing spaces with underscores and slashes with dashes.

    """
    # FIXME: Quick Hack to avoid trouble caused by slashes in the list's name
    path_fragments = [f.replace('/', '-') for f in fragments]

    full_path = os.path.join(RESULTS_DIR_ROOT, *path_fragments)
    return full_path.replace(' ', '_')


def mkdir(*path):
    """
    Quick helper to check if a directory exists (starting from
    RESULTS_DIR_ROOT) and create it if not.

    path should be a list of path fragments (they will be joined together
    along with RESULTS_DIR_ROOT).

    """
    full_path = normpath(*path)
    if not os.path.exists(full_path):
        _LOGGER.info('Creating directory %s', full_path)
        os.makedirs(full_path)


def wipe_dir(*dirpath):
    """ rm `dirpath` and all its content and recreates it. """
    full_path = normpath(*dirpath)
    if os.path.exists(full_path):
        _LOGGER.info('%s directory already exixts - Wiping it out', dirpath)
        os.system('rm -r %s' % full_path)
    mkdir(*dirpath)


def get_current_files():
    """
    Generate a list of all files currently present. Useful to `git -rm` them
    later on if needed.

    """
    files = []
    for current, _, files_ in os.walk(BLOBS_ROOT):
        files.extend(os.path.join(current, f) for f in files_)
    for current, _, files_ in os.walk(TREE_ROOT):
        files.extend(os.path.join(current, f) for f in files_)
    return files


def write_card(blob_path, tree_path, data):
    """
    Write the passed data to ``blob_path`` and create a symlink to it at
    ``tree_path``.

    """
    rel_path = os.path.relpath(blob_path, os.path.dirname(tree_path))
    with open(blob_path, 'w') as out:
        out.write(data)
    os.symlink(rel_path, tree_path)


# --- Trello Api ---

def dump_yaml(card_data, tree_path):
    """
    Dump the card data as YAML and create a symlink pointing to it in the
    the ``current`` directory tree.

    """
    blob_path = normpath('raw_tickets', card_data['id']) + '.yaml'
    tree_path += '.yaml'
    write_card(blob_path, tree_path, toyaml(card_data))


def dump_txt(card_data, tree_path):
    """
    Dump a more readable representation of the passed ``card`` and associate a
    symlink with it (basically the same as ``dump_yaml``, with some formatting
    added.

    """
    comments = u'\n'.join(
        TXT_DUMP_COMMENTS_TEMPLATE.format(comment=comment)
        for comment in card_data['comments']
    )
    # Ugly fix: the name param returned by the trello API is NOT unicode,
    # so we have to convert it here to avoid crashes.
    card_data['name'] = unicode(card_data['name'], 'utf8')
    txt = TXT_DUMP_TEMPLATE.format(card=card_data, comments=comments)

    blob_path = normpath('raw_tickets', card_data['id']) + '.txt'
    tree_path += '.txt'
    write_card(blob_path, tree_path, txt.encode('utf-8'))


def dl_card(card, tree_path):
    """ Format a single card data and save it as a YAML file. """
    _LOGGER.info('    Retrieving data for card %s...', card.name)
    card_data = {}

    # Grabbing almost all fields, execpt the ``trello_list`` and a few others
    # which are manually serialized below (``checklists`` & ``comments``).
    # Note: the trello_list field is misleading, it is actually a Board object.
    for key in ('id', 'name', 'description', 'closed', 'url', 'member_ids',
                'short_id', 'board_id', 'list_id', 'labels', 'badges', 'due',
                'checked'):
        card_data[key] = getattr(card, key)

    # Manually grab the comments, in order to trim the user info associated with
    # them.
    # We don't really care about all this user info here, and they will mess up
    # history if the user changes his avater or something. We'll only keep
    # his id (the only field we really need) and username (for readability),
    # and get rid of the redundant idMemberCreator field.
    card_data['comments'] = []
    for comm in card.comments:
        del comm['idMemberCreator']
        # This field is no longer returned for deleted accounts.
        member_info = comm.get('memberCreator')
        if member_info:
            for key in ('avatarHash', 'fullName', 'initials'):
                del member_info[key]
        else:
            comm['memberCreator'] = {'username': 'COMPTE SUPPRIME'}
        card_data['comments'].append(comm)

    # Grab checklists
    # NOTE: We need to "parse" them separately as py-trello wraps
    # them in its own object, unlike the comments which are just
    # stored on the card as a dict.
    # TODO: is there more data here ? We don't really use them currently...
    cl_data = [
        {
            'id': cl.id,
            'name': cl.name,
            'items': cl.items,
        }
        for cl in card.checklists
    ]
    card_data['checklists'] = cl_data

    dump_yaml(card_data, tree_path)
    dump_txt(card_data, tree_path)

def retrieve_trello_data():
    """
    Get all data accessible to the current user from trello and save it on
    disk.

    """

    client = trello.TrelloClient(
        api_key=API_KEY, api_secret=API_SECRET, token=TOKEN
    )

    # Retrieve individual board data
    for board in client.list_boards():

        # Skipping the default board.
        if board.name == 'Welcome Board':
            continue

        _LOGGER.info('Retrieving data for board %s...', board.name)
        board_dirname = '%s_%s' % (str(board.id), board.name)

        # Wipe out the current directory for this board and recreate it.
        wipe_dir('current', board_dirname)

        # Iterate over all cards, and write its data to the ``raw_tickets``
        # directory, along with a symlink in the ``current`` structure.

        # First deal with the closed cards (symlink goes to a special
        # ``archives`` subdir for the current board).
        closed_cards = board.closed_cards()
        if closed_cards:
            _LOGGER.info('Retrieving data for archived cards...')
            wipe_dir('current', board_dirname, 'archives')

            for closed_card in closed_cards:
                closed_card.fetch()
                tree_path = normpath(
                    'current', board_dirname, 'archives', '%s_%s' % (
                        closed_card.short_id, closed_card.name)
                )
                dl_card(closed_card, tree_path)

        # Then deal with the opened cards, putting the symlink in the right
        # subdir (corresponding to the list it's associated with).
        for list_ in board.all_lists():
            _LOGGER.info('  Retrieving data for list %s...', list_.name)
            list_name_path = '%s_%s' % (str(list_.id), list_.name)
            mkdir('current', board_dirname, list_name_path)

            for card in list_.list_cards():
                card.fetch()
                tree_path = normpath(
                    'current', board_dirname, list_name_path, '%s_%s' % (
                        card.short_id, card.name)
                )
                dl_card(card, tree_path)


# --- Git repo management ---

def _git_cmd(*args, **kwargs):
    """
    Quick helper. Prefix the  `args` array with "git" and return the system's
    error code, logging errors if any.

    Passing a ``log_errors`` keyword parameter set to False will skip the
    logging.

    """
    args = ['git'] + list(args)
    p = subprocess.Popen(args,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, errors = p.communicate()
    rcode = p.returncode
    _LOGGER.debug('Executed cmd: %s', ' '.join(args))
    _LOGGER.debug('Got: %d', rcode)
    if rcode != 0 and kwargs.get('log_errors', True):
        _LOGGER.error(errors)
    return rcode


def get_repo(repo_path):
    """ Clone the trellobackup repository into the result path. """
    _LOGGER.info('Retrieving the %s repository, cloning into %s...',
                 GIT_REPO_URL, repo_path)
    _git_cmd('clone', GIT_REPO_URL, repo_path)


def git_commit():
    """ Commit all retrieved files. """
    _git_cmd('add', '.')
    commit_msg = 'backup - %s' % datetime.now()
    # Git commit return errcode 1 if there is nothing to commit,
    # hence the log_errors param set to False to avoid generating
    # useless sentry errors.
    _git_cmd('commit', '-m', commit_msg, log_errors=False)


def git_pull():
    """
    Pull latest changes from the backup repo.

    This should not be strictly necessary, but might avoid troubles if
    we run the script from different machines.

    """
    _LOGGER.info('Refreshing local repo...')
    _git_cmd('pull', 'origin', 'master')


def git_push():
    """ Push the committed changes to the backup repo. """
    _LOGGER.info('Pushing data to %s', GIT_REPO_URL)
    _git_cmd('push', 'origin', 'master')


def gitit(repo_path, prev_files):
    """ Wrapper to handle the whole git backup process. """

    with temporary_chdir(repo_path):

        # Remove any file that is no longer present.
        current_files = get_current_files()
        for old_file in prev_files:
            if old_file not in current_files:
                _git_cmd('rm', old_file)

        git_commit()
        git_push()


def main():
    """ Script entry point. """

    # Get the backup repo if it does not exist
    if not os.path.exists(RESULTS_DIR_ROOT):
        get_repo(RESULTS_DIR_ROOT)
    # Refresh it
    with temporary_chdir(RESULTS_DIR_ROOT):
        git_pull()

    # Grab a list of the files we already have, to handle deletions leter on.
    with temporary_chdir('results'):
        current_files = get_current_files()
    # Get & Git the latest data
    retrieve_trello_data()
    gitit(RESULTS_DIR_ROOT, current_files)


if __name__ == '__main__':
    import sys
    sys.exit(main())

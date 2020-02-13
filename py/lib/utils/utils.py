""" Utility functions"""
from collections import defaultdict
from subprocess import Popen, PIPE, CalledProcessError


def autovivify(levels=1, final=dict):
    """Creates multi-level dictionary based on defaultdict

    Args:
        levels (int): number of levels
        final (type): type of innermost level
    """
    return (defaultdict(final) if levels < 2 else
            defaultdict(lambda: autovivify(levels - 1, final)))


def cleanup_protein_id(protein):
    """ This function was added for back compatibility with early versions
    of Fama reference datasets.
    For compatibility with old format of protein IDs uncomment next 4 lines

    Args:
        protein (str): protein identifier

    Todo:
        remove
    """
    # if len(protein.split('_')) > 1:
    #    return "_".join(protein.split('_')[1:])
    # else:
    #    return protein
    return protein


def sanitize_file_name(filename):
    """ Replaces unsafe symbols in filenames

    Args:
        filename (str): file name
    """
    filename = filename.replace(' ', '_')
    filename = filename.replace("'", "")
    filename = filename.replace('"', '')
    return filename


def singleton(cls):
    """Implements singleton design pattern"""
    instances = {}

    def getinstance(*args, **kwargs):
        """Creates singleton instance of cls, if not exists, and returns it"""
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return getinstance


def run_external_program(cmd):
    """Starts new process with given arguments

    Args:
        cmd (list of str): external command with parameters and options
    Raises:
        CalledProcessError if external program fails
    """
    with Popen(cmd, stdout=PIPE, bufsize=1, universal_newlines=True) as proc:
        for line in proc.stdout:
            print(line, end='')
    if proc.returncode != 0:
        # Suppress false positive no-member error (see https://github.com/PyCQA/pylint/issues/1860)
        # pylint: disable=no-member
        raise CalledProcessError(proc.returncode, proc.args)


def run_external_program_ignoreerror(cmd):
    """Starts new process with given arguments. Use with caution: does not exits on error!

    Args:
        cmd (list of str): external command with parameters and options
    """
    with Popen(cmd, stdout=PIPE, bufsize=1, universal_newlines=True) as proc:
        for line in proc.stdout:
            print(line, end='')
    if proc.returncode != 0:
        # Suppress false positive no-member error (see https://github.com/PyCQA/pylint/issues/1860)
        # pylint: disable=no-member
        print('Called process returned error', proc.returncode, proc.args)

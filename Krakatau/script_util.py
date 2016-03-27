from __future__ import print_function

import collections
import errno
from functools import partial
import hashlib
import os
import os.path
import platform
import zipfile

# Various utility functions for the top level scripts (decompile.py, assemble.py, disassemble.py)

copyright = '''Krakatau  Copyright (C) 2012-16  Robert Grosse
This program is provided as open source under the GNU General Public License.
See LICENSE.TXT for more details.
'''

def findFiles(target, recursive, prefix):
    if target.endswith('.jar'):
        with zipfile.ZipFile(target, 'r') as archive:
            targets = [name for name in archive.namelist() if name.endswith(prefix)]
    else:
        if recursive:
            assert os.path.isdir(target)
            targets = []

            for root, dirs, files in os.walk(target):
                targets += [os.path.join(root, fname) for fname in files if fname.endswith(prefix)]
        else:
            return [target]
    return targets

def normalizeClassname(name):
    if name.endswith('.class'):
        name = name[:-6]
    # Replacing backslashes is ugly since they can be in valid classnames too, but this seems the best option
    return name.replace('\\','/').replace('.','/')

# Windows stuff
illegal_win_chars = frozenset('<>;:|?*\\/"')
pref_disp_chars = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$0123456789')

# Prevent creating filename parts matching the legacy device filenames. While Krakatau can create these files
# just fine thanks to using \\?\ paths, the resulting files are impossible to open or delete in Windows Explorer
# or with similar tools, so they are a huge pain to deal with. Therefore, we don't generate them at all.
illegal_parts = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8',
    'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']

def isPartOk(s, prev):
    if not 1 <= len(s) <= 200:
        return False
    if s.upper() in illegal_parts:
        return False
    if s.lower() in prev:
        return prev[s.lower()] == s
    # avoid collision with hashed parts
    if len(s) >= 34 and s[-34:-32] == '__':
        return False

    if min(s) <= '\x1f' or max(s) >= '\x7f':
        return False
    return illegal_win_chars.isdisjoint(s)

def isPathOk(s, prevs):
    if len(s) > 32000:
        return False
    parts = s.split('/')
    return 0 < len(parts) < 750

def sanitizePart(s, suffix, prev):
    # make sure that suffix is never in any parts so we don't get a collision after adding it
    if isPartOk(s, prev) and suffix not in s:
        return s
    ok = ''.join(c for c in s if c in pref_disp_chars)
    return ok[:8] + '__' + hashlib.md5(s.encode('utf8')).hexdigest()

def winSanitizePath(base, suffix, prevs, s):
    if isPathOk(s, prevs):
        parts = s.split('/')
        sparts = [sanitizePart(p, suffix, prevs[i]) for i,p in enumerate(parts)]
        for i, sp in enumerate(sparts):
            prevs[i][sp.lower()] = sp
        path = '\\'.join(sparts)
    else:
        path = '__' + hashlib.md5(s.encode('utf8')).hexdigest()
        prevs[0][path.lower()] = path
    return '\\\\?\\{}\\{}{}'.format(base, path, suffix)

def otherMakePath(base, suffix, s):
    return os.path.join(base, *s.split('/')) + suffix

class DirectoryWriter(object):
    def __init__(self, base_path, suffix):
        if base_path is None:
            base_path = os.getcwdu()
        else:
            base_path = base_path.decode('utf8')
            base_path = os.path.abspath(base_path)

        osname = platform.system().lower()
        if 'win' in osname and 'darwin' not in osname and 'cygwin' not in osname:
            prevs = collections.defaultdict(dict) # keep track of previous paths to detect case-insensitive collisions
            self.makepath = partial(winSanitizePath, base_path, suffix, prevs)
        else:
            self.makepath = partial(otherMakePath, base_path, suffix)

    def write(self, cname, data):
        out = self.makepath(cname)
        dirpath = os.path.dirname(out)

        try:
            if dirpath:
                os.makedirs(dirpath)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

        with open(out,'wb') as f:
            f.write(data)
        return out

    def __enter__(self): pass
    def __exit__(self, *args): pass

class JarWriter(object):
    def __init__(self, base_path, suffix):
        self.zip = zipfile.ZipFile(base_path, mode='w')
        self.suffix = suffix

    def write(self, cname, data):
        self.zip.writestr(cname + self.suffix, data)
        return 'zipfile'

    def __enter__(self): self.zip.__enter__()
    def __exit__(self, *args): self.zip.__exit__(*args)

def makeWriter(base_path, suffix):
    if base_path is not None:
        if base_path.endswith('.zip') or base_path.endswith('.jar'):
            return JarWriter(base_path, suffix)
    return DirectoryWriter(base_path, suffix)

###############################################################################
def ignore(*args, **kwargs):
    pass

class Logger(object):
    def __init__(self, level):
        lvl = ['info','warning'].index(level)
        self.info = print if lvl <= 0 else ignore
        self.warn = print if lvl <= 1 else ignore

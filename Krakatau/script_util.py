import platform, os, os.path, zipfile
import collections, hashlib

copyright = '''Krakatau  Copyright (C) 2012-13  Robert Grosse
This program is provided as open source under the GNU General Public License.
See LICENSE.TXT for more details.
'''

def findFiles(target, recursive, prefix):
    if target.endswith('.jar'):
        with zipfile.ZipFile(target, 'r') as archive:
            targets = [name for name in archive.namelist() if name.endswith(prefix)]
    else:
        if recursive:
            assert(os.path.isdir(target))
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

#Windows stuff
illegal_win_chars = frozenset('<>;:|?*\\/"')
pref_disp_chars = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$0123456789')
def isPartOk(s, prev):
    if not 1 <= len(s) <= 200:
        return False
    if s.lower() in prev:
        return prev[s.lower()] == s
    #avoid collision with hashed parts
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
    #make sure that suffix is never in any parts so we don't get a collision after adding it
    if isPartOk(s, prev) and suffix not in s:
        return s
    ok = ''.join(c for c in s if c in pref_disp_chars)
    return ok[:8] + '__' + hashlib.md5(s).hexdigest()

def winSanitizePath(base, s, suffix, prevs):
    if isPathOk(s, prevs):
        parts = s.split('/')
        sparts = [sanitizePart(p, suffix, prevs[i]) for i,p in enumerate(parts)]
        for i, sp in enumerate(sparts):
            prevs[i][sp.lower()] = sp
        path = '\\'.join(sparts)
    else:
        path = '__' + hashlib.md5(s).hexdigest()
        prevs[0][path.lower()] = path
    return '\\\\?\\{}\\{}{}'.format(base, path, suffix)

def fileDirOut(base_path, suffix):
    if base_path is None:
        base_path = os.getcwd()
    else:
        base_path = os.path.abspath(base_path)

    if 'win' in platform.system().lower():
        prevs = collections.defaultdict(dict) #keep track of previous paths to detect case-insensitive collisions
        makepath = lambda s:winSanitizePath(base_path, s, suffix, prevs)
    else:
        makepath = lambda s:os.path.join(base_path, *s.split('/')) + suffix

    def write(cname, data):
        out = makepath(cname)
        dirpath = os.path.dirname(out)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath)

        with open(out,'wb') as f:
            f.write(data)
        return out
    return write
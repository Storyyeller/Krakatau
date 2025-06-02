import collections
import errno
import os
import shutil
import zipfile
from cStringIO import StringIO

def createdir(basedir):
    try:
        os.makedirs(basedir)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise

def read(filename):
    with open(filename, 'rb') as f:
        return f.read()

def read_zip(data, ext):
    with zipfile.ZipFile(StringIO(data), 'r') as zf:
        return sorted((n, zf.read(n)) for n in zf.namelist() if n.endswith(ext))

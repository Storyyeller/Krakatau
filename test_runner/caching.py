import collections
import errno
from functools import partial, wraps
import json
import hashlib
import os
import shutil
import tempfile

from test_runner.file_util import read, createdir

CACHE_ROOT = tempfile.gettempdir()
print 'Using {} as cache root. Set TMPDIR env var to change'.format(CACHE_ROOT)



BLOB_DIR = os.path.join(CACHE_ROOT, 'blobs')
createdir(BLOB_DIR)


def shash(data):
    return hashlib.sha256(data).hexdigest()


HashedPath = collections.namedtuple('HashedPath', 'path hash origin')
def get_hashed_path(path, origin=None):
    origin = origin or path
    if path.startswith(BLOB_DIR):
        h, ext = path.rpartition('/')[-1].split('.')
        return HashedPath(path=path, hash=h, origin=origin)
    return HashedPath(path=path, hash=shash(read(path)), origin=origin)

def cache(name, temp=False):
    cache_root = CACHE_ROOT
    blob_dir = BLOB_DIR

    basedir = os.path.join(cache_root, name)
    if temp:
        print 'clearing', basedir
        shutil.rmtree(basedir, ignore_errors=True)
    createdir(basedir)



    def dec(func):
        @wraps(func)
        def inner(inpath, outext, allow_error=False, **extra_args):
            target_h = inpath.hash
            if extra_args:
                s = json.dumps(extra_args, sort_keys=True)
                target_h = shash(target_h + s)


            hash_loc = os.path.join(basedir, '{}{}'.format(target_h, outext))
            if not os.path.exists(hash_loc):
                # Create a temporary directory to run the command in
                tdir = tempfile.mkdtemp()
                res = func(inpath, os.path.join(tdir, 'temp' + outext), **extra_args)
                # Res can be either HashedPath (on success) or CommandOutput (on failure)
                if not isinstance(res, HashedPath):
                    if not allow_error:
                        print 'Unexpected error running ' + ' '.join(res.cmd)
                        print 'Command returned {}'.format(res.returncode)
                        print 'stdout: ' + res.stdout
                        print 'stderr: ' + res.stderr
                        assert allow_error
                    shutil.rmtree(tdir)
                    return res

                outpath = res.path
                out_hash = res.hash
                out_base = '{}{}'.format(out_hash, outext)
                blob_path = os.path.join(blob_dir, out_base)
                shutil.copy2(outpath, blob_path)
                with open(hash_loc, 'w') as f:
                    f.write(out_base)
                # print name, 'cached', hash_loc, blob_path

                # Clean up the temporary directory now that the output file has been copied into the cache dir
                shutil.rmtree(tdir)
            else:
                out_base = read(hash_loc).decode()
                blob_path = os.path.join(blob_dir, out_base)
                # print name, 'cache hit', target_h, '->', out_base

            origin = (name, inpath) + tuple(sorted(['{}={}'.format(arg_name, val) for arg_name, val in extra_args.items()]))
            return get_hashed_path(blob_path, origin=origin)
        return inner
    return dec

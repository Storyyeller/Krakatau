#!/usr/bin/env python2
'''Script for testing the decompiler.

On the first run tests/*.test files will be created with expected results for each test.

To generate a test's result file, run with `--create-only`.
To add a new test, add the relevant classfile and an entry in registry.
'''
import os, shutil, tempfile, time
import hashlib
import subprocess
import cPickle as pickle
import optparse

import decompile
from tests.decompiler import registry

# Note: If this script is moved, be sure to update this path.
krakatau_root = os.path.dirname(os.path.abspath(__file__))
cache_location = os.path.join(krakatau_root, 'tests', '.cache')
test_location = os.path.join(krakatau_root, 'tests', 'decompiler')
class_location = os.path.join(test_location, 'classes')

class TestFailed(Exception):
    pass

def execute(args, cwd):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return process.communicate()

def read(filename):
    with open(filename, 'rb') as f:
        return f.read()

def shash(data): return hashlib.sha256(data).hexdigest()

def createDir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass
    assert(os.path.isdir(path))

def runJava(target, cases, path):
    digest = shash(read(os.path.join(path, target + '.class')))
    cache = os.path.join(cache_location, digest)
    try:
        results = pickle.loads(read(cache))
    except IOError:
        print 'failed to load cache', digest
        results = {}

    modified = False
    for args in cases:
        if args not in results:
            print 'Executing {} w/ args {}'.format(target, args)
            results[args] = execute(['java', target] + list(args), cwd=path)
            modified = True

    if modified:
        with open(cache, 'wb') as f:
            pickle.dump(results, f, -1)
        print 'updated cache', digest
    return results

def runJavaAndCompare(target, testcases, temppath):
    expected = runJava(target, testcases, class_location)
    actual = runJava(target, testcases, temppath)
    for args in testcases:
        if expected[args] != actual[args]:
            message = ['Failed test {} w/ args {}:'.format(target, args)]
            if actual[args][0] != expected[args][0]:
                message.append('  expected stdout: ' + repr(expected[args][0]))
                message.append('  actual stdout  : ' + repr(actual[args][0]))
            if actual[args][1] != expected[args][1]:
                message.append('  expected stderr: ' + repr(expected[args][1]))
                message.append('  actual stderr  : ' + repr(actual[args][1]))
            raise TestFailed('\n'.join(message))

def performTest(target, tempbase=tempfile.gettempdir()):
    temppath = os.path.join(tempbase, target)

    cpath = [decompile.findJRE(), class_location]
    if cpath[0] is None:
        raise RuntimeError('Unable to locate rt.jar')

    createDir(temppath)
    decompile.decompileClass(cpath, targets=[target], outpath=temppath, add_throws=True)
    # out, err = execute(['java',  '-jar', 'procyon-decompiler-0.5.25.jar', os.path.join(class_location, target+'.class')], '.')
    # if err:
    #     print 'Decompile errors:', err
    #     return False
    # with open(os.path.join(temppath, target+'.java'), 'wb') as f:
    #     f.write(out)

    print 'Attempting to compile'
    _, stderr = execute(['javac', target+'.java', '-g:none'], cwd=temppath)
    if 'error:' in stderr: # Ignore compiler unchecked warnings by looking for 'error:'
        raise TestFailed('Compile failed: ' + stderr)
    runJavaAndCompare(target, map(tuple, registry[target]), temppath)

if __name__ == '__main__':
    op = optparse.OptionParser(usage='Usage: %prog [options] [testfile(s)]',
                               description=__doc__)
    opts, args = op.parse_args()

    # Set up the tests list.
    targets = args if args else sorted(registry)

    createDir(cache_location)
    results = {}
    start_time = time.time()
    for test in targets:
        print 'Doing test {}...'.format(test)
        results[test] = False
        try:
            performTest(test)
        except TestFailed as e:
            print e
        except Exception:
            import traceback
            traceback.print_exc()
        else:
            results[test] = True

    print '\nTest results:'
    for test in targets:
        print '  {}: {}'.format(test, 'Pass' if results[test] else 'Fail')
    print '{}/{} tests passed'.format(sum(results.itervalues()), len(results))
    print 'elapsed time:', time.time()-start_time

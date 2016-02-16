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

from Krakatau import script_util
from Krakatau.assembler.tokenize import AsssemblerError
import decompile
import disassemble
import assemble
import tests

# Note: If this script is moved, be sure to update this path.
krakatau_root = os.path.dirname(os.path.abspath(__file__))
cache_location = os.path.join(krakatau_root, 'tests', '.cache')
dec_class_location = os.path.join(krakatau_root, 'tests', 'decompiler', 'classes')
dis_class_location = os.path.join(krakatau_root, 'tests', 'disassembler', 'classes')
tempbase = tempfile.gettempdir()

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

def compileJava(target, path):
    digest = shash(read(os.path.join(path, target + '.java')))
    cache = os.path.join(cache_location, digest)
    out_location = os.path.join(path, target + '.class')

    try:
        shutil.copy2(cache, out_location)
    except IOError:
        print 'Attempting to compile'
        _, stderr = execute(['javac', target+'.java', '-g:none'], cwd=path)
        if 'error:' in stderr: # Ignore compiler unchecked warnings by looking for 'error:'
            raise TestFailed('Compile failed: ' + stderr)
        shutil.copy2(out_location, cache)

def runJavaAndCompare(target, testcases, temppath, class_location):
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

def runDecompilerTest(target):
    print 'Running decompiler test {}...'.format(test)
    temppath = os.path.join(tempbase, target)

    cpath = [decompile.findJRE(), dec_class_location]
    if cpath[0] is None:
        raise RuntimeError('Unable to locate rt.jar')

    createDir(temppath)
    decompile.decompileClass(cpath, targets=[target], outpath=temppath, add_throws=True)
    compileJava(target, temppath)
    runJavaAndCompare(target, map(tuple, tests.decompiler.registry[target]), temppath, dec_class_location)

def runDisassemblerTest(target):
    print 'Running disassembler test {}...'.format(test)
    temppath = os.path.join(tempbase, target)
    classloc = os.path.join(dis_class_location, target + '.class')
    jloc = os.path.join(temppath, target + '.j')

    createDir(temppath)
    disassemble.disassembleClass(disassemble.readFile, targets=[classloc], outpath=temppath)
    pairs = assemble.assembleClass(jloc)
    for name, data in pairs:
        with open(os.path.join(temppath, name + '.class'), 'wb') as f:
            f.write(data)
        assert name == target

    runJavaAndCompare(target, map(tuple, tests.disassembler.registry[target]), temppath, dis_class_location)

def runAssemblerTest(fname, exceptFailure):
    print 'Running assembler test', os.path.basename(fname)
    error = False
    try:
        assemble.assembleClass(fname, fatal=True)
    except AsssemblerError:
        error = True
    assert error == exceptFailure

def runAssemblerTests(basedir, exceptFailure):
    for fname in os.listdir(basedir):
        if fname.endswith('.j'):
            runAssemblerTest(os.path.join(basedir, fname), exceptFailure)

if __name__ == '__main__':
    op = optparse.OptionParser(usage='Usage: %prog [options] [testfile(s)]',
                               description=__doc__)
    opts, args = op.parse_args()
    createDir(cache_location)

    start_time = time.time()
    for test in sorted(tests.decompiler.registry):
        runDecompilerTest(test)
    for test in sorted(tests.disassembler.registry):
        runDisassemblerTest(test)

    runAssemblerTests(os.path.join(krakatau_root, 'tests', 'assembler', 'bad'), True)
    runAssemblerTests(os.path.join(krakatau_root, 'tests', 'assembler', 'good'), False)
    runAssemblerTests(os.path.join(krakatau_root, 'tests', 'decompiler', 'source'), False)
    runAssemblerTests(os.path.join(krakatau_root, 'tests', 'disassembler', 'source'), False)

    print 'All tests passed!'
    print 'elapsed time:', time.time()-start_time

#!/usr/bin/env python2
'''Script for testing the decompiler.

On the first run tests/*.test files will be created with expected results for each test.

To generate a test's result file, run with `--create-only`.
To add a new test, add the relevant classfile and an entry in registry.
'''
import os, shutil, tempfile, time
import hashlib
import json
import optparse
import subprocess

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
    print 'executing command', args, 'in directory', cwd
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

###############################################################################
def _runJava(target, in_fname, argslist):
    tdir = tempfile.mkdtemp()
    shutil.copy2(in_fname, os.path.join(tdir, target + '.class'))

    for args in argslist:
        results = execute(['java', target] + list(args), cwd=tdir)
        assert 'VerifyError' not in results[1]
        assert 'ClassFormatError' not in results[1]
        yield results

    shutil.rmtree(tdir)

def runJava(target, in_fname, argslist):
    digest = shash(read(in_fname) + json.dumps(argslist).encode())
    cache = os.path.join(cache_location, digest)
    try:
        with open(cache, 'r') as f:
            return json.load(f)
    except IOError:
        print 'failed to load cache', digest

    results = list(_runJava(target, in_fname, argslist))
    with open(cache, 'w') as f:
        json.dump(results, f)
    # reparse json to ensure consistent results in 1st time vs cache hit
    with open(cache, 'r') as f:
        return json.load(f)

def compileJava(target, in_fname):
    assert not in_fname.endswith('.class')
    digest = shash(read(in_fname))
    cache = os.path.join(cache_location, digest)

    if not os.path.exists(cache):
        tdir = tempfile.mkdtemp()
        shutil.copy2(in_fname, os.path.join(tdir, target + '.java'))

        _, stderr = execute(['javac', target + '.java', '-g:none'], cwd=tdir)
        if 'error:' in stderr: # Ignore compiler unchecked warnings by looking for 'error:'
            raise TestFailed('Compile failed: ' + stderr)
        shutil.copy2(os.path.join(tdir, target + '.class'), cache)

        shutil.rmtree(tdir)
    return cache

def runJavaAndCompare(target, testcases, good_fname, new_fname):
    expected_results = runJava(target, good_fname, testcases)
    actual_results = runJava(target, new_fname, testcases)

    for args, expected, actual in zip(testcases, expected_results, actual_results):
        if expected != actual:
            message = ['Failed test {} w/ args {}:'.format(target, args)]
            if actual[0] != expected[0]:
                message.append('  expected stdout: ' + repr(expected[0]))
                message.append('  actual stdout  : ' + repr(actual[0]))
            if actual[1] != expected[1]:
                message.append('  expected stderr: ' + repr(expected[1]))
                message.append('  actual stderr  : ' + repr(actual[1]))
            raise TestFailed('\n'.join(message))

def runDecompilerTest(target):
    print 'Running decompiler test {}...'.format(test)
    temppath = os.path.join(tempbase, target)

    cpath = [decompile.findJRE(), dec_class_location]
    if cpath[0] is None:
        raise RuntimeError('Unable to locate rt.jar')

    createDir(temppath)
    decompile.decompileClass(cpath, targets=[target], outpath=temppath, add_throws=True)
    new_fname = compileJava(target, os.path.join(temppath, target + '.java'))

    testcases = map(tuple, tests.decompiler.registry[target])
    good_fname = os.path.join(dec_class_location, target + '.class')
    runJavaAndCompare(target, testcases, good_fname, new_fname)

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

    new_fname = os.path.join(temppath, target + '.class')
    testcases = map(tuple, tests.disassembler.registry[target])
    good_fname = os.path.join(dis_class_location, target + '.class')
    runJavaAndCompare(target, testcases, good_fname, new_fname)

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

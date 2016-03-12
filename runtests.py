import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time

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

def runDecompilerTest(target, testcases):
    print 'Running decompiler test {}...'.format(target)
    tdir = tempfile.mkdtemp()

    cpath = [decompile.findJRE(), dec_class_location]
    if cpath[0] is None:
        raise RuntimeError('Unable to locate rt.jar')

    decompile.decompileClass(cpath, targets=[target], outpath=tdir, add_throws=True)
    new_fname = compileJava(target, os.path.join(tdir, target + '.java'))

    # testcases = map(tuple, tests.decompiler.registry[target])
    good_fname = os.path.join(dec_class_location, target + '.class')
    runJavaAndCompare(target, testcases, good_fname, new_fname)
    shutil.rmtree(tdir)

def runDisassemblerTest(target, testcases):
    print 'Running disassembler test {}...'.format(target)
    tdir = tempfile.mkdtemp()

    classloc = os.path.join(dis_class_location, target + '.class')
    jloc = os.path.join(tdir, target + '.j')

    disassemble.disassembleClass(disassemble.readFile, targets=[classloc], outpath=tdir)
    pairs = assemble.assembleClass(jloc)
    new_fname = os.path.join(tdir, target + '.class')

    for name, data in pairs:
        assert name == target
        with open(new_fname, 'wb') as f:
            f.write(data)

    good_fname = os.path.join(dis_class_location, target + '.class')
    runJavaAndCompare(target, testcases, good_fname, new_fname)
    shutil.rmtree(tdir)

def runAssemblerTest(fname, exceptFailure):
    print 'Running assembler test', os.path.basename(fname)
    error = False
    try:
        assemble.assembleClass(fname, fatal=True)
    except AsssemblerError:
        error = True
    assert error == exceptFailure

def runTest(data):
    try:
        {
            'decompiler': runDecompilerTest,
            'disassembler': runDisassemblerTest,
            'assembler': runAssemblerTest,
        }[data[0]](*data[1:])
    except Exception:
        import traceback
        return 'Test {} failed:\n'.format(data) + traceback.format_exc()

def addAssemblerTests(testlist, basedir, exceptFailure):
    for fname in os.listdir(basedir):
        if fname.endswith('.j'):
            testlist.append(('assembler', os.path.join(basedir, fname), exceptFailure))

if __name__ == '__main__':
    args = sys.argv[1] if len(sys.argv) > 1 else 'dsa'

    try:
        os.mkdir(cache_location)
    except OSError:
        pass

    start_time = time.time()
    testlist = []

    if 'd' in args:
        for target, testcases in sorted(tests.decompiler.registry.items()):
            testlist.append(('decompiler', target, map(tuple, testcases)))
    if 's' in args:
        for target, testcases in sorted(tests.disassembler.registry.items()):
            testlist.append(('disassembler', target, map(tuple, testcases)))

    if 'a' in args:
        test_base = os.path.join(krakatau_root, 'tests')
        addAssemblerTests(testlist, os.path.join(test_base, 'assembler', 'bad'), True)
        addAssemblerTests(testlist, os.path.join(test_base, 'assembler', 'good'), False)
        addAssemblerTests(testlist, os.path.join(test_base, 'decompiler', 'source'), False)
        addAssemblerTests(testlist, os.path.join(test_base, 'disassembler', 'source'), False)

    print len(testlist), 'test cases found'
    for error in multiprocessing.Pool(processes=5).map(runTest, testlist):
        if error:
            print error
            break
    else:
        print 'All {} tests passed!'.format(len(testlist))
        print 'elapsed time:', time.time()-start_time

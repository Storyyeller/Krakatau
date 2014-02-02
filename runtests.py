'''Script for testing the decompiler.

On the first run tests/*.test files will be created with expected results for each test.

To generate a test's result file, run with `--create-only`.
To add a new test, add the relevant classfile and an entry in tests.registry.
'''
import os, shutil, tempfile
import subprocess
import cPickle as pickle
import optparse

import decompile
import tests

# Note: If this script is moved, be sure to update this path.
krakatau_root = os.path.dirname(os.path.abspath(__file__))
test_location = os.path.join(krakatau_root, 'tests')
class_location = os.path.join(test_location, 'classes')

def execute(args, cwd):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return process.communicate()

def createTest(target):
    print 'Generating {}.test'.format(target)
    results = [execute(['java', target] + arg_list, cwd=class_location)
               for arg_list in tests.registry[target]]
    testfile = os.path.join(test_location, target) + '.test'
    with open(testfile, 'wb') as f:
        pickle.dump(results, f, -1)
    return results

def loadTest(name):
    with open(os.path.join(test_location, name) + '.test', 'rb') as f:
        return pickle.load(f)

def performTest(target, expected_results, tempbase=tempfile.gettempdir()):
    temppath = os.path.join(tempbase, target)

    cpath = [decompile.findJRE(), class_location]
    if None in cpath:
        raise RuntimeError('Unable to locate rt.jar')

    # Clear any pre-existing files and create directory if necessary
    # try:
    #     shutil.rmtree(temppath)
    # except OSError as e:
    #     print e
    try:
        os.mkdir(temppath)
    except OSError as e:
        print e
    assert(os.path.isdir(temppath))

    decompile.decompileClass(cpath, targets=[target], outpath=temppath)
    # out, err = execute(['java',  '-jar', 'procyon-decompiler-0.5.24.jar', os.path.join(class_location, target+'.class')], '.')
    # if err:
    #     print 'Decompile errors:', err
    #     return False
    # with open(os.path.join(temppath, target+'.java'), 'wb') as f:
    #     f.write(out)

    print 'Attempting to compile'
    _, stderr = execute(['javac', target+'.java', '-g:none'], cwd=temppath)
    if stderr:
        print 'Compile failed:'
        print stderr
        return False

    cases = tests.registry[target]
    for args, expected in zip(cases, expected_results):
        print 'Executing {} w/ args {}'.format(target, args)
        result = execute(['java', target] + list(args), cwd=temppath)
        if result != expected:
            print 'Failed test {} w/ args {}:'.format(target, args)
            if result[0] != expected[0]:
                print '  expected stdout:', repr(expected[0])
                print '  actual stdout  :', repr(result[0])
            if result[1] != expected[1]:
                print '  expected stderr:', repr(expected[1])
                print '  actual stderr  :', repr(result[1])
            return False
    return True

if __name__ == '__main__':
    op = optparse.OptionParser(usage='Usage: %prog [options] [testfile(s)]',
                               description=__doc__)
    op.add_option('-c', '--create-only', action='store_true',
                  help='Generate cache of expected results')
    opts, args = op.parse_args()

    # Set up the tests list.
    targets = args if args else sorted(tests.registry)

    results = {}
    for test in targets:
        print 'Doing test {}...'.format(test)
        try:
            expected_results = loadTest(test)
        except IOError:
            expected_results = createTest(test)

        if not opts.create_only:
            results[test] = performTest(test, expected_results)

    print '\nTest results:'
    for test in targets:
        print '  {}: {}'.format(test, 'Pass' if results[test] else 'Fail')
    print '{}/{} tests passed'.format(sum(results.itervalues()), len(results))
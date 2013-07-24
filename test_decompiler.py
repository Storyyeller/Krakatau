'''Script for testing the decompiler.

On the first run (or when the --create-all-testfiles flag is passed),
tests/*.test files will be created with the results of running each program in
the tests/classes/*.class directory.

To generate a test's result file, run with `-c testname`.
To add a new test, add it to the test_registry then generate the result file.
'''
import os
import subprocess
import cPickle as pickle
import optparse
import tempfile

import decompile

# Note: If this script is move, be sure to update this path.
krakatau_root = os.path.dirname(__file__)
test_location = os.path.join(krakatau_root, 'tests')
class_location = os.path.join(test_location, 'classes')

# Mapping from test name -> tuple of argument lists.
test_registry = {
    'ArgumentTypes': (['42', 'false'], ['43', 'true'], ['1', '1', '1']),
    'ArrayTest': ([], ['x']),
    'BadInnerTest': ([],),
    'BoolizeTest': ([],),
    'ControlFlow': ([], ['.Na', 'q'], ['ddKK', '-2'], ['hB7X', '-1'],
                    ['R%%X', '0', '0'], ['>OE=.K', '#FF'],
                    ['95', ' ', 'x', 'x']),
    'DoubleEdge': ([], ['x']),
    'DuplicateInit': ([], ['5', '-7'], ['x', 'x', 'x']),
    'floattest': ([],),
    'NullInference': ([], ['alice'], ['bob', 'carol']),
    'OddsAndEnds': ([], ['x'], ['42'], ['4'], ['-2'], ['-0x567'], ['-5678']),
    'OldVersionTest': ([],),
    'SkipJSR': ([], ['x', 'x', 'x', 'x']),
    'splitnew': ([], ['-0'], ['-0', ''], ['-0', '', '', ''],
                 ['-0', '', '', '', '', '', '', '', '', '', '', '', '', '']),
    'StaticInitializer': ([],),
    'Switch': ([], ['0'], ['0', '1'], ['0', '1', '2'], ['0', '1', '2', '3'],
               ['0', '1', '2', '3', '4']),
    'Synchronized': ([], [''], ['', '', '', '']),
    'TryCatchTest': ([], ['bad'], ['bad', 'boy'], ['good'], [u'f'], ['=', '='],
                     ['<<', '<', ':', '>', '>>']),
    'UnicodeTest': ([],),
    'whilesize': ([], ['x'], ['x', 'x'], ['x', 'xx', 'x'],
                  ['The', 'Quick', 'Brown', 'Fox', 'Jumped', 'Over', 'The', 'Lazy', 'Dogs.'],
                  ['46', '08'], ['4608']),
}

def execute(args, cwd):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return process.communicate()

def createTest(target):
    print 'Generating {}.test...'.format(target)
    results = [execute(['java', target] + arg_list, cwd=class_location)
               for arg_list in test_registry[target]]
    testfile = os.path.join(test_location, target) + '.test'
    with open(testfile, 'wb') as f:
        pickle.dump(results, f)
    print 'Done.'

def loadTest(name):
    with open(os.path.join(test_location, name) + '.test', 'rb') as f:
        return pickle.load(f)

def performTest(target):
    temppath = tempfile.gettempdir()
    cpath = [decompile.findJRE(), class_location]
    if None in cpath:
        raise RuntimeError('Unable to locate rt.jar')

    # Clear any pre-existing source file, in case decompileClass fails silently.
    try:
        os.remove(os.path.join(temppath, target + '.java'))
    except OSError:
        pass
    decompile.decompileClass(cpath, targets=[target], outpath=temppath)

    print 'Attempting to compile'
    _, stderr = execute(['javac', target+'.java', '-g:none'], cwd=temppath)
    if stderr:
        print 'Compile failed:'
        print stderr
        return False

    cases = test_registry[target]
    expected_results = loadTest(target)
    for args, expected in zip(cases, expected_results):
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

def parseArgs():
    op = optparse.OptionParser(usage='Usage: %prog [options] [testfile(s)]',
                               description=__doc__)
    op.add_option('-c','--create-testfile', metavar='TEST', action='append',
                  type=str, default=[],
                  help='Generate a *.test file required for testing.')
    op.add_option('--create-all-testfiles', action='store_true',
                  help='Generate all *.test files from class files in ' + class_location)
    opts, args = op.parse_args()
    # Do some quick argument validation.
    for test in args:
        if test not in test_registry:
            op.error('{} is not a valid test name.'.format(repr(test)))
    # Set up the tests list.
    if args:
        opts.tests = args
    elif not opts.create_testfile:
        opts.tests = [x[:-5] for x in os.listdir(test_location) if x.endswith('.test')]
    else:
        opts.tests = []
        for testfile in opts.create_testfile:
            createTest(testfile)
            opts.tests.append(testfile)
    # Do any required test file generation.
    if opts.create_all_testfiles or not opts.tests:
        print 'Generating *.test files from classes in', class_location
        opts.tests = []
        for test_class in os.listdir(class_location):
            if test_class.endswith('.class'):
                createTest(test_class[:-6])
                opts.tests.append(test_class[:-6])
    return opts

def runTests():
    opts = parseArgs()
    results = {}
    for test in opts.tests:
        print 'Doing test {}...'.format(test)
        results[test] = performTest(test)
    print '\nAll tests finished:'
    for test in opts.tests:
        print '  {}: {}'.format(test, 'Pass' if results[test] else 'Fail')
    print ''
    print '{}/{} tests passed'.format(sum(results.itervalues()), len(results))

if __name__ == '__main__':
    runTests()

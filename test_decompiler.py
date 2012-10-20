import os, shutil, sys
import subprocess
import cPickle

import decompile
test_location = os.path.join('Krakatau','tests')
class_location = os.path.join('Krakatau','tests','classes')

def clearFolder(path):
    for fpath in os.listdir(path):
        fpath = os.path.join(path, fpath)
        if os.path.isfile(fpath):
            os.unlink(fpath)
        else:
            shutil.rmtree(fpath)

def execute(args, cwd):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return process.communicate()

def createTest(target, inputs, cpath=class_location):
    cases = []
    for args in inputs:
        result = execute(['java', target] + list(args), cwd=cpath)
        cases.append((args,result))
    testdata = target, cases

    with open(os.path.join(test_location, target) + '.test', 'wb') as f:
        cPickle.dump(testdata, f)
    print 'Test created at ', os.path.join(test_location, target)

def loadTest(name):
    with open(os.path.join(test_location, name) + '.test', 'rb') as f:
        return cPickle.load(f)

def performTest(temppath, testdata, cpath=class_location):
    target, cases = testdata

    clearFolder(temppath)
    cpath = [decompile.findJRE(), cpath]
    decompile.decompileClass(cpath, targets=[target], outpath=temppath)

    print 'Attempting to compile'
    out, err = execute(['javac', target+'.java'] + '-g:none -target 1.5'.split(), cwd=temppath)
    if err:
        print out, err
        return False

    for args, expected in cases:
        result = execute(['java', target] + list(args), cwd=temppath)
        if result != expected:
            print 'expected', expected
            print 'actual', result
            return False
    return True

if __name__ == "__main__":
    tempdir = sys.argv[1]

    if len(sys.argv) > 2:
        tests = sys.argv[2:]
    else:
        tests = [x[:-5] for x in os.listdir(test_location) if x.endswith('.test')]
        print 'Tests found:', tests 
    
    results = {}
    for test in tests:
        print 'Doing test', test
        results[test] = performTest(tempdir, loadTest(test))
        if not results[test]:
            print 'Failed!!!'

    print '\n'.join(map(str, results.items()))
    if all(results.values()):
        print 'All tests passed'

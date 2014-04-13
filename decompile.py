import os.path
import time, random

import Krakatau
import Krakatau.ssa
from Krakatau.error import ClassLoaderError
from Krakatau.environment import Environment
from Krakatau.java import javaclass
from Krakatau.verifier.inference_verifier import verifyBytecode
from Krakatau import script_util

def findJRE():
    try:
        home = os.environ['JAVA_HOME']
        path = os.path.join(home, 'jre', 'lib', 'rt.jar')
        if os.path.isfile(path):
            return path

        #For macs
        path = os.path.join(home, 'bundle', 'Classes', 'classes.jar')
        if os.path.isfile(path):
            return path
    except Exception as e:
        pass

def _stats(s):
    bc = len(s.blocks)
    vc = sum(len(b.unaryConstraints) for b in s.blocks)
    return '{} blocks, {} variables'.format(bc,vc)

def _print(s):
    from Krakatau.ssa.printer import SSAPrinter
    return SSAPrinter(s).print_()

def makeGraph(m):
    v = verifyBytecode(m.code)
    s = Krakatau.ssa.ssaFromVerified(m.code, v)

    if s.procs:
        # s.mergeSingleSuccessorBlocks()
        # s.removeUnusedVariables()
        s.inlineSubprocs()

    # print _stats(s)
    s.condenseBlocks()
    s.mergeSingleSuccessorBlocks()
    s.removeUnusedVariables()
    # print _stats(s)
    s.constraintPropagation()
    s.disconnectConstantVariables()
    s.simplifyJumps()
    s.mergeSingleSuccessorBlocks()
    s.removeUnusedVariables()
    # print _stats(s)
    return s

def deleteUnusued(cls):
    #Delete attributes we aren't going to use
    #pretty hackish, but it does help when decompiling large jars
    for e in cls.fields + cls.methods:
        del e.class_, e.attributes, e.static
    for m in cls.methods:
        del m.native, m.abstract, m.isConstructor
        del m.code
    del cls.version, cls.this, cls.super, cls.env
    del cls.interfaces_raw, cls.cpool
    del cls.attributes

def decompileClass(path=[], targets=None, outpath=None, skipMissing=False):
    writeout = script_util.fileDirOut(outpath, '.java')

    e = Environment()
    for part in path:
        e.addToPath(part)

    start_time = time.time()
    # random.shuffle(targets)
    with e: #keep jars open
        for i,target in enumerate(targets):
            print 'processing target {}, {} remaining'.format(target, len(targets)-i)

            try:
                c = e.getClass(target)
                source = javaclass.generateAST(c, makeGraph).print_()
            except ClassLoaderError as err:
                if skipMissing:
                    print 'failed to decompile {} due to missing or invalid class {}'.format(target, err.data)
                    continue
                else:
                    raise

            #The single class decompiler doesn't add package declaration currently so we add it here
            if '/' in target:
                package = 'package {};\n\n'.format(target.replace('/','.').rpartition('.')[0])
                source = package + source

            filename = writeout(c.name, source)
            print 'Class written to', filename
            print time.time() - start_time, ' seconds elapsed'
            deleteUnusued(c)

if __name__== "__main__":
    print script_util.copyright

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-path',action='append',help='Semicolon seperated paths or jars to search when loading classes')
    parser.add_argument('-out',help='Path to generate source files in')
    parser.add_argument('-nauto', action='store_true', help="Don't attempt to automatically locate the Java standard library. If enabled, you must specify the path explicitly.")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-skip', action='store_true', help="Skip classes when an error occurs due to missing dependencies")
    parser.add_argument('target',help='Name of class or jar file to decompile')
    args = parser.parse_args()

    path = []
    if not args.nauto:
        print 'Attempting to automatically locate the standard library...'
        found = findJRE()
        if found:
            print 'Found at ', found
            path.append(found)
        else:
            print 'Unable to find the standard library'

    if args.path:
        for part in args.path:
            path.extend(part.split(';'))

    if args.target.endswith('.jar'):
        path.append(args.target)

    targets = script_util.findFiles(args.target, args.r, '.class')
    targets = map(script_util.normalizeClassname, targets)
    decompileClass(path, targets, args.out, args.skip)
import os.path, zipfile
import time, random

import Krakatau
import Krakatau.ssa
from Krakatau.environment import Environment
from Krakatau.java import javaclass
from Krakatau.verifier.inference_verifier import verifyBytecode
import Krakatau.assembler.disassembler

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

def makeGraph(m):
    v = verifyBytecode(m.code)
    s = Krakatau.ssa.ssaFromVerified(m.code, v)
    if s.procs:
        s.mergeSingleSucessorBlocks()
        s.removeUnusedVariables()
        s.inlineSubprocs()
    s.condenseBlocks()
    s.mergeSingleSucessorBlocks()
    s.removeUnusedVariables()
    s.pessimisticPropagation() #WARNING - currently does not work if any output variables have been pruned already
    s.pruneInferredUnreachable()
    s.disconnectConstantVariables()

    s.simplifyJumps()
    s.mergeSingleSucessorBlocks()
    s.condenseBlocks()
    s.removeUnusedVariables() #todo - make this a loop
    return s

def decompileClass(path=[], targets=None, outpath=None, disassemble=False):
    if outpath is None:
        outpath = os.getcwd()

    e = Environment()
    for part in path:
        e.addToPath(part)

    # targets = targets[::-1]
    start_time = time.time()
    # random.shuffle(targets)
    for i,target in enumerate(targets):
        print 'processing target {}, {} remaining'.format(target, len(targets)-i)
        c = e.getClass(target)

        if disassemble:
            source = Krakatau.assembler.disassembler.disassemble(c)
        else:
            deco = javaclass.ClassDecompiler(c, makeGraph)
            source = deco.generateSource()
            #The single class decompiler doesn't add package declaration currently so we add it here
            if '/' in target:
                package = 'package {};\n\n'.format(target.replace('/','.').rpartition('.')[0])
                source = package + source

        outpath2 = outpath        
        if os.path.isdir(outpath2):
            outpath2 = os.path.join(outpath2, *c.name.split('/'))
            outpath2 += '.java' if not disassemble else '.j'

        dirpath = os.path.dirname(outpath2)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath)

        print 'writing generated source to', outpath2  
        with open(outpath2,'w') as f:
            f.write(source)
        print time.time() - start_time, ' seconds elapsed'

if __name__== "__main__":
    print 'Krakatau  Copyright (C) 2012-13  Robert Grosse'

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-path',action='append',help='Semicolon seperated paths or jars to search when loading classes')
    parser.add_argument('-out',help='Path to generate source files in')
    parser.add_argument('-nauto', action='store_true', help="Don't attempt to automatically locate the Java standard library. If enabled, you must specify the path explicitly.")
    parser.add_argument('-dis', action='store_true', help="Disassemble only, instead of decompiling.")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
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

    target = args.target
    if target.endswith('.jar'):
        path.append(target)
        with zipfile.ZipFile(target, 'r') as archive:
            targets = [name[:-6] for name in archive.namelist() if name.endswith('.class')]
            targets = sorted(targets)
        print len(targets), 'classfiles found in the jar'
    else:
        if args.r:
            assert(os.path.isdir(target))
            targets = []
            for root, dirs, files in os.walk(target):
                targets += [os.path.join(root, fname[:-6]).replace('\\','/') for fname in files if fname.endswith('.class')]
            print len(targets), 'classfiles found in directory'
        else:
            if target.endswith('.class'):
                target = target[:-6]
            targets = [target.replace('.','/')]
    decompileClass(path, targets, args.out, args.dis)

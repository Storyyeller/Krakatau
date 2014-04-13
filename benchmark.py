import os.path
import time, random

import Krakatau
import Krakatau.ssa
from Krakatau.environment import Environment
from Krakatau.java import javaclass
from Krakatau.verifier.inference_verifier import verifyBytecode
from Krakatau import script_util
from util import Timer

def makeGraph(m):
    v = verifyBytecode(m.code)
    s = Krakatau.ssa.ssaFromVerified(m.code, v)

    # print _stats(s)
    if s.procs:
        # s.mergeSingleSuccessorBlocks()
        # s.removeUnusedVariables()
        s.inlineSubprocs()

    s.condenseBlocks()
    s.mergeSingleSuccessorBlocks()
    # print _stats(s)
    s.removeUnusedVariables()
    s.constraintPropagation()
    s.disconnectConstantVariables()
    s.simplifyJumps()
    s.mergeSingleSuccessorBlocks()
    s.removeUnusedVariables()
    # print _stats(s)
    return s

def decompileClass(path=[], targets=None, outpath=None):
    e = Environment()
    for part in path:
        e.addToPath(part)

    with e, Timer('warming up'):
        for i,target in enumerate(targets):
            for _ in range(40):
                c = e.getClass(target)
                source = javaclass.generateAST(c, makeGraph).print_()

    with e, Timer('testing'):
        for i,target in enumerate(targets):
            for _ in range(200):
                c = e.getClass(target)
                source = javaclass.generateAST(c, makeGraph).print_()

if __name__== "__main__":
    print 'Krakatau  Copyright (C) 2012-13  Robert Grosse'

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-path',action='append',help='Semicolon seperated paths or jars to search when loading classes')
    parser.add_argument('-out',help='Path to generate source files in')
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    args = parser.parse_args()

    path = []
    if args.path:
        for part in args.path:
            path.extend(part.split(';'))

    targets = ['sun/text/normalizer/Utility']
    decompileClass(path, targets, args.out)
import os.path
import time, random

import Krakatau
import Krakatau.ssa
from Krakatau.environment import Environment
from Krakatau.java import javaclass, visitor
from Krakatau.verifier.inference_verifier import verifyBytecode
from Krakatau import script_util

from decompile import makeGraph
from util import Timer

def decompileClass(path=[], targets=None):
    e = Environment()
    for part in path:
        e.addToPath(part)

    with e, Timer('warming up'):
        for i,target in enumerate(targets):
            for _ in range(1000):
                c = e.getClass(target)
                source = visitor.DefaultVisitor().visit(javaclass.generateAST(c, makeGraph, False))

    with e, Timer('testing'):
        for i,target in enumerate(targets):
            for _ in range(500):
                c = e.getClass(target)
                source = visitor.DefaultVisitor().visit(javaclass.generateAST(c, makeGraph, False))

if __name__== "__main__":
    print 'Krakatau  Copyright (C) 2012-15  Robert Grosse'

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau benchmark')
    parser.add_argument('-path',action='append',help='Semicolon seperated paths or jars to search when loading classes')
    args = parser.parse_args()

    path = []
    if args.path:
        for part in args.path:
            path.extend(part.split(';'))

    targets = ['javax/swing/plaf/nimbus/ToolBarSouthState']
    decompileClass(path, targets)
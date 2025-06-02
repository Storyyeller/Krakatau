#!/usr/bin/env python2
from __future__ import print_function

import json
import os.path
import time, random, subprocess, functools

import Krakatau
import Krakatau.ssa
from Krakatau.error import ClassLoaderError
from Krakatau.environment import Environment
from Krakatau.java import javaclass, visitor
from Krakatau.java.stringescape import escapeString
from Krakatau.verifier.inference_verifier import verifyBytecode
from Krakatau import script_util

def findJRE():
    try:
        home = os.environ.get('JAVA_HOME')
        if home:
            path = os.path.join(home, 'jre', 'lib', 'rt.jar')
            if os.path.isfile(path):
                return path

            # For macs
            path = os.path.join(home, 'bundle', 'Classes', 'classes.jar')
            if os.path.isfile(path):
                return path

        # Ubuntu and co
        out = subprocess.Popen(['update-java-alternatives', '-l'], stdout=subprocess.PIPE).communicate()[0]
        basedir = out.split('\n')[0].rpartition(' ')[-1]
        path = os.path.join(basedir, 'jre', 'lib', 'rt.jar')
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

def makeGraph(opts, m):
    v = verifyBytecode(m.code)
    s = Krakatau.ssa.ssaFromVerified(m.code, v, opts)

    if s.procs:
        # s.mergeSingleSuccessorBlocks()
        # s.removeUnusedVariables()
        s.inlineSubprocs()

    # print(_stats(s))
    s.condenseBlocks()
    s.mergeSingleSuccessorBlocks()
    s.removeUnusedVariables()
    # print(_stats(s))

    s.copyPropagation()
    s.abstractInterpert()
    s.disconnectConstantVariables()

    s.simplifyThrows()
    s.simplifyCatchIgnored()
    s.mergeSingleSuccessorBlocks()
    s.mergeSingleSuccessorBlocks()
    s.removeUnusedVariables()
    # print(_stats(s))
    return s

def deleteUnusued(cls):
    # Delete attributes we aren't going to use
    # pretty hackish, but it does help when decompiling large jars
    for e in cls.fields + cls.methods:
        del e.class_, e.attributes, e.static
    for m in cls.methods:
        del m.native, m.abstract, m.isConstructor
        del m.code
    del cls.version, cls.this, cls.super, cls.env
    del cls.interfaces_raw, cls.cpool
    del cls.attributes

def decompileClass(path=[], targets=None, outpath=None, skip_errors=False, add_throws=False, magic_throw=False, dump_ssa=False):
    outext = '.json' if dump_ssa else '.java'
    out = script_util.makeWriter(outpath, outext)

    e = Environment()
    for part in path:
        e.addToPath(part)


    start_time = time.time()
    # random.shuffle(targets)
    with e, out:
        printer = visitor.DefaultVisitor()
        for i,target in enumerate(targets):
            print('processing target {}, {} remaining'.format(target, len(targets)-i))

            try:
                c = e.getClass(target.decode('utf8'))
                makeGraphCB = functools.partial(makeGraph, magic_throw)
                # Hack to dump SSA graph for debugging purposes
                if dump_ssa:
                    results = [makeGraphCB(method).to_json() for method in c.methods if method.code is not None]
                    source = json.dumps(results, indent=2)
                # Regular decompilation
                else:
                    source = printer.visit(javaclass.generateAST(c, makeGraphCB, skip_errors, add_throws=add_throws))
            except Exception as err:
                if not skip_errors:
                    raise
                if isinstance(err, ClassLoaderError):
                    print('Failed to decompile {} due to missing or invalid class {}'.format(target, err.data))
                else:
                    import traceback
                    print(traceback.format_exc())
                continue

            # The single class decompiler doesn't add package declaration currently so we add it here
            if '/' in target and not dump_ssa:
                package = 'package {};\n\n'.format(escapeString(target.replace('/','.').rpartition('.')[0]))
                source = package + source

            filename = out.write(c.name.encode('utf8'), source)
            print('Class written to', filename)
            print(time.time() - start_time, ' seconds elapsed')
            deleteUnusued(c)
        print(len(e.classes) - len(targets), 'extra classes loaded')

if __name__== "__main__":
    print(script_util.copyright)

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-path',action='append',help='Semicolon seperated paths or jars to search when loading classes')
    parser.add_argument('-out',help='Path to generate source files in')
    parser.add_argument('-nauto', action='store_true', help="Don't attempt to automatically locate the Java standard library. If enabled, you must specify the path explicitly.")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-skip', action='store_true', help="Upon errors, skip class or method and continue decompiling")
    parser.add_argument('-xmagicthrow', action='store_true')
    parser.add_argument('-xdumpssa', action='store_true')
    parser.add_argument('-xaddthrows', action='store_true')
    parser.add_argument('target',help='Name of class or jar file to decompile')
    args = parser.parse_args()

    path = []
    if not args.nauto:
        print('Attempting to automatically locate the standard library...')
        found = findJRE()
        if found:
            print('Found at ', found)
            path.append(found)
        else:
            print('Unable to find the standard library')

    if args.path:
        for part in args.path:
            path.extend(part.split(';'))

    if args.target.endswith('.jar'):
        path.append(args.target)

    targets = script_util.findFiles(args.target, args.r, '.class')
    targets = map(script_util.normalizeClassname, targets)
    decompileClass(path, targets, args.out, args.skip, magic_throw=args.xmagicthrow, dump_ssa=args.xdumpssa, add_throws=args.xaddthrows)

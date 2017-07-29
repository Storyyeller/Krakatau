#!/usr/bin/env python2

# ---------------------------------------------------------------
# Assembler / Disassembler in one script.
# For Krakatau commit 86dfd43d148f65226ae4c020aff7421637e3756d
# ---------------------------------------------------------------

from __future__ import print_function

import functools
import os.path
import time, zipfile, sys
import os.path, time
import Krakatau
from Krakatau import script_util
from Krakatau.classfileformat.reader import Reader
from Krakatau.classfileformat.classdata import ClassData
from Krakatau.assembler.disassembly import Disassembler
from Krakatau.assembler import parse

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


def readArchive(archive, name):
    with archive.open(name.decode('utf8')) as f:
        return f.read()


def readFile(filename):
    with open(filename, 'rb') as f:
        return f.read()


def disassembleSub(readTarget, out, targets, roundtrip=False, outputClassName=True):
    start_time = time.time()
    with out:
        for i, target in enumerate(targets):
            print('processing target {}, {}/{} remaining'.format(target, len(targets)-i, len(targets)))

            data = readTarget(target)
            clsdata = ClassData(Reader(data))

            if outputClassName:
                name = clsdata.pool.getclsutf(clsdata.this)
            else:
                name = target.rpartition('.')[0] or target

            output = StringIO()
            # output = sys.stdout
            Disassembler(clsdata, output.write, roundtrip=roundtrip).disassemble()

            filename = out.write(name, output.getvalue())
            if filename is not None:
                print('Class written to', filename)
                print(time.time() - start_time, ' seconds elapsed')


def assembleSource(source, basename, fatal=False):
    source = source.replace('\t', '  ') + '\n'
    return list(parse.assemble(source, basename, fatal=fatal))


def assembleClass(filename):
    basename = os.path.basename(filename)
    with open(filename, 'rU') as f:
        source = f.read()
    return assembleSource(source, basename)


def assemble(args):
    log = script_util.Logger('warning' if args.q else 'info')
    log.info(script_util.copyright)

    out = script_util.makeWriter(args.out, '.class')
    targets = script_util.findFiles(args.target, args.r, '.j')

    start_time = time.time()
    with out:
        for i, target in enumerate(targets):
            log.info('Processing file {}, {}/{} remaining'.format(target, len(targets)-i, len(targets)))

            pairs = assembleClass(target)
            for name, data in pairs:
                filename = out.write(name, data)
                log.info('Class written to', filename)
    print('Total time', time.time() - start_time)


def disassemble(args):
    print(script_util.copyright)

    targets = script_util.findFiles(args.target, args.r, '.class')

    jar = args.path
    if jar is None and args.target.endswith('.jar'):
        jar = args.target

    out = script_util.makeWriter(args.out, '.j')
    if jar is not None:
        with zipfile.ZipFile(jar, 'r') as archive:
            readFunc = functools.partial(readArchive, archive)
            disassembleSub(readFunc, out, targets, roundtrip=args.roundtrip)
    else:
        disassembleSub(readFile, out, targets, roundtrip=args.roundtrip)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Krakatau bytecode assembler/disassembler')
    parser.add_argument('-d', action='store_true', help='Disassemble mode')
    parser.add_argument('-out', help='Path to generate files in')
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-q', action='store_true', help="Only display warnings and errors (asm mode only)")
    parser.add_argument('-path', help='Jar to look for class in (disasm mode only)')
    parser.add_argument('-roundtrip', action='store_true', help='Create assembly file that can roundtrip to original binary (disasm mode only).')
    parser.add_argument('target', help='Name of file to assemble or name of class or jar file to decompile')
    args = parser.parse_args()

    if args.d:
        disassemble(args)
    else:
        assemble(args)

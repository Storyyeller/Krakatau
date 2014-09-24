import os.path

import Krakatau
from Krakatau.assembler import tokenize, parse, assembler
from Krakatau import script_util

def assembleClass(log, filename, makeLineNumbers, jasmode, debug=0):
    basename = os.path.basename(filename)
    assembly = open(filename, 'rb').read()
    if assembly.startswith('\xca\xfe') or assembly.startswith('\x50\x4b\x03\x04'):
        log.warn('Error: You appear to have passed a jar or classfile instead of an assembly file')
        log.warn('Perhaps you meant to invoke the disassembler instead?')
        return []
    assembly = assembly.decode('utf8')

    assembly = '\n'+assembly+'\n' #parser expects newlines at beginning and end
    lexer = tokenize.makeLexer(debug=debug)
    parser = parse.makeParser(debug=debug)
    parse_trees = parser.parse(assembly, lexer=lexer)
    return parse_trees and [assembler.assemble(tree, makeLineNumbers, jasmode, basename) for tree in parse_trees]

if __name__== "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Krakatau bytecode assembler')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-g', action='store_true', help="Add line number information to the generated class")
    parser.add_argument('-jas', action='store_true', help="Enable Jasmin compatibility mode")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-q', action='store_true', help="Only display warnings and errors")
    parser.add_argument('target',help='Name of file to assemble')
    args = parser.parse_args()

    log = script_util.Logger('warning' if args.q else 'info')
    log.info(script_util.copyright)

    out = script_util.makeWriter(args.out, '.class')
    targets = script_util.findFiles(args.target, args.r, '.j')

    with out:
        for i, target in enumerate(targets):
            log.info('Processing file {}, {}/{} remaining'.format(target, len(targets)-i, len(targets)))
            pairs = assembleClass(log, target, args.g, args.jas)

            for name, data in pairs:
                filename = out.write(name, data)
                log.info('Class written to', filename)

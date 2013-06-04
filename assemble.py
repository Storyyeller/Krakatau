import os.path

import Krakatau
from Krakatau.assembler import tokenize, parse, assembler
from Krakatau import script_util

def assembleClass(filename, makeLineNumbers, jasmode, debug=0):
    basename = os.path.basename(filename)
    assembly = open(filename, 'rb').read()
    assembly = '\n'+assembly+'\n' #parser expects newlines at beginning and end

    lexer = tokenize.makeLexer(debug=debug)
    parser = parse.makeParser(debug=debug)
    parse_trees = parser.parse(assembly, lexer=lexer)
    return parse_trees and [assembler.assemble(tree, makeLineNumbers, jasmode, basename) for tree in parse_trees]

if __name__== "__main__":
    print script_util.copyright

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau bytecode assembler')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-g', action='store_true', help="Add line number information to the generated class")
    parser.add_argument('-jas', action='store_true', help="Enable Jasmin compatibility mode")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('target',help='Name of file to assemble')
    args = parser.parse_args()

    targets = script_util.findFiles(args.target, args.r, '.j')
    base_path = args.out if args.out is not None else os.getcwd()

    for i, target in enumerate(targets):
        print 'Processing file {}, {}/{} remaining'.format(target, len(targets)-i, len(targets))
        pairs = assembleClass(target, args.g, args.jas)

        # if pairs is None:
        #     print 'Assembly of ', target, 'failed!'
        #     continue

        for name, data in pairs:
            filename = script_util.writeFile(base_path, name, '.class', data)
            print 'Class written to', filename
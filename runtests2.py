import ast
import collections
import errno
from functools import partial, wraps
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from cStringIO import StringIO

start_time = time.time()


import tests # registry listing which tests to run with which arguments
from test_runner.file_util import read_zip, read, createdir
from test_runner.caching import get_hashed_path, CACHE_ROOT
from test_runner.actions import assembleR, assemblePy2, disassemblePy2, disassembleR, run_java, CommandOutput, assemblePy3, disassemblePy3, decompilePy2, run_javac
from test_runner.file_comparison import check_compare_binaries

###################################################################################################
### Preprocess sources ############################################################################
PP_MARKER = b'###preprocess###\n'
RANGE_RE = re.compile(br'###range(\([^)]+\)):')
def preprocess(source, fname):
    if source.startswith(PP_MARKER):
        print 'Preprocessing', fname
        buf = bytearray()
        pos = len(PP_MARKER)
        dstart = source.find(b'###range', pos)
        while dstart != -1:
            buf += source[pos:dstart]
            dend = source.find(b'###', dstart + 3)
            m = RANGE_RE.match(source, dstart, dend)
            pattern = source[m.end():dend].decode('utf8')
            for i in range(*ast.literal_eval(m.group(1).decode('utf8'))):
                buf += pattern.format(i, ip1=i+1).encode()
            pos = dend + 3
            dstart = source.find(b'###range', pos)
        buf += source[pos:]
        source = bytes(buf)
        # with open('temp/' + os.path.basename(fname), 'wb') as f:
        #     f.write(source)
    return source.decode('utf8')

PREPROCESS_DIR = os.path.join(CACHE_ROOT, 'preprocessed')
createdir(PREPROCESS_DIR)
def preprocess_file(path, fname):
    with open(path, 'rb') as f:
        data = f.read()
    data = preprocess(data, fname).encode('utf8')
    new_path = os.path.join(PREPROCESS_DIR, fname)
    with open(new_path, 'wb') as f:
        f.write(data)
    return new_path
###################################################################################################


def test_roundtrip(apath1, name, input_is_zip, no_short_code=False, skip_pydis=False, skip_pyasm=False):
    outext = '.zip' if input_is_zip else '.class'

    # skip jars with no classfiles inside
    if input_is_zip:
        if not read_zip(read(apath1.path), '.class'):
            return

    jpaths = []
    jpaths.append(disassembleR(apath1, '.j', roundtrip=True, no_short_code=no_short_code))
    if not skip_pydis:
        jpaths.append(disassemblePy2(apath1, '.j', roundtrip=True))
        jpaths.append(disassemblePy3(apath1, '.j', roundtrip=True))

    for jpath in jpaths:
        # print 'jpath', jpath
        check_compare_binaries(apath1, assembleR(jpath, outext), input_is_zip)
        if not skip_pyasm:
            check_compare_binaries(apath1, assemblePy2(jpath, outext), input_is_zip)
            check_compare_binaries(apath1, assemblePy3(jpath, outext), input_is_zip)


    ### Nonroundtrip ##################################################
    outpaths = []
    jpaths = []
    jpaths.append(disassembleR(apath1, '.j', roundtrip=False, no_short_code=no_short_code))
    if not skip_pydis:
        jpaths.append(disassemblePy2(apath1, '.j', roundtrip=False))
        jpaths.append(disassemblePy3(apath1, '.j', roundtrip=False))

    for jpath in jpaths:
        print 'jpath', jpath
        outpaths.append(assembleR(jpath, outext))
        if not skip_pyasm:
            outpaths.append(assemblePy2(jpath, outext))
            outpaths.append(assemblePy3(jpath, outext))




    outhashes = set()
    return [ap for ap in outpaths if not ap.hash in outhashes and not outhashes.add(ap.hash)]



def run_and_compare_java(apath1, apath2, params):
    expected = run_java(apath1, '.json', args=params)
    actual = run_java(apath2, '.json', args=params)
    if expected.hash != actual.hash:
        print 'expected', read(expected.path)
        print 'actual', read(actual.path)
        assert expected == actual




### Now find and run the actual tests ###

for basedir in ['tests/assembler/good', 'examples']:
    for fname in sorted(os.listdir(basedir)):
        name = fname.rpartition('.')[0]
        print '\nrunning test', name

        jpath = preprocess_file(os.path.join(basedir, fname), fname)
        jpath = get_hashed_path(jpath)

        skip_pydis = name == 'bs0'
        test_roundtrip(assemblePy2(jpath, '.zip'), name, True, skip_pydis=skip_pydis)
        test_roundtrip(assemblePy3(jpath, '.zip'), name, True, skip_pydis=skip_pydis)
        test_roundtrip(assembleR(jpath, '.zip'), name, True, skip_pydis=skip_pydis)



for basedir in ['tests/assembler/bad']:
    for fname in sorted(os.listdir(basedir)):
        name = fname.rpartition('.')[0]

        skip = [
            'code_in_record',
            'named_record_in_record',
            'record_in_code',
        ]
        if name in skip:
            continue


        print '\nrunning test', name

        jpath = preprocess_file(os.path.join(basedir, fname), fname)
        jpath = get_hashed_path(jpath)

        # Failures are indicated by returning CommandOutput
        res = assembleR(jpath, '.zip', allow_error=True)
        assert isinstance(res, CommandOutput)
        res = assemblePy2(jpath, '.zip', allow_error=True)
        assert isinstance(res, CommandOutput)
        res = assemblePy3(jpath, '.zip', allow_error=True)
        assert isinstance(res, CommandOutput)



for name, arglists in sorted(tests.disassembler.registry.items()):
    is_jar = name in 'AnnotationsTest MethodParametersTest PatternMatching'.split()
    jvm_ver = 'jdk-18' if name in 'MethodParametersTest PatternMatching RecursiveDynamic'.split() else 'java-8-oracle'
    fname = 'tests/disassembler/classes/{}{}'.format(name, '.jar' if is_jar else '.class')

    print '\nrunning test', name
    params = is_jar, name, jvm_ver, arglists
    apath1 = get_hashed_path(fname)
    for apath2 in test_roundtrip(apath1, name, is_jar):
        test_roundtrip(apath2, name, is_jar)
        run_and_compare_java(apath1, apath2, params)



for name, arglists in sorted(tests.decompiler.registry.items()):
    is_jar = name in ''.split()
    jvm_ver = 'jdk-18' if name in 'For'.split() else 'java-8-oracle'
    fname = 'tests/decompiler/classes/{}{}'.format(name, '.jar' if is_jar else '.class')

    print '\nrunning test', name
    params = is_jar, name, jvm_ver, arglists
    apath1 = get_hashed_path(fname)
    for apath2 in test_roundtrip(apath1, name, is_jar):
        test_roundtrip(apath2, name, is_jar)
        run_and_compare_java(apath1, apath2, params)

    decompiled = decompilePy2(apath1, '.java', target=name)
    compiled = run_javac(decompiled, '.class', jvm_ver=jvm_ver, target=name)
    run_and_compare_java(apath1, compiled, params)



print 'All tests passed. Elapsed time: {}'.format(time.time() - start_time)

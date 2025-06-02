import collections
from functools import partial
import json
import os
import shutil
import subprocess
import tempfile

from test_runner.caching import cache, get_hashed_path

INVALIDATE_PY=1
INVALIDATE_RS=0

CommandOutput = collections.namedtuple('CommandOutput', 'cmd returncode stdout stderr')


def execute(args, cwd='.'):
    print 'executing', ' '.join(args)
    if cwd != '.':
        print '\tcwd=', cwd

    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    stdout, stderr = process.communicate()
    return CommandOutput(args, process.returncode, stdout.decode('utf8', errors='replace'), stderr.decode('utf8', errors='replace'))

# Return CommandOutput if execution had an error, return None on success
def execute_error(args):
    out = execute(args)
    if out.returncode or out.stderr:
        return out
    return None


@cache('assemblePy2', temp=INVALIDATE_PY)
def assemblePy2(inpath, outpath):
    args = ['python', '../Krakatau/assemble.py', inpath.path, '-out', outpath]
    return execute_error(args) or get_hashed_path(outpath)


@cache('disassemblePy2', temp=INVALIDATE_PY)
def disassemblePy2(inpath, outpath, roundtrip):
    args = ['python', '../Krakatau/disassemble.py', inpath.path, '-out', outpath]
    if roundtrip:
        args.append('-roundtrip')
    return execute_error(args) or get_hashed_path(outpath)

@cache('assemblePy3', temp=INVALIDATE_PY)
def assemblePy3(inpath, outpath):
    args = ['python3', '../Krakatau/assemble.py', inpath.path, '-out', outpath]
    return execute_error(args) or get_hashed_path(outpath)


@cache('disassemblePy3', temp=INVALIDATE_PY)
def disassemblePy3(inpath, outpath, roundtrip):
    args = ['python3', '../Krakatau/disassemble.py', inpath.path, '-out', outpath]
    if roundtrip:
        args.append('-roundtrip')
    return execute_error(args) or get_hashed_path(outpath)



@cache('assembleR', temp=INVALIDATE_RS)
def assembleR(inpath, outpath):
    # args = ['../krakatau2/target/debug/krak2', 'asm', inpath.path, '--out', outpath]
    args = ['../krakatau2/target/release/krak2', 'asm', inpath.path, '--out', outpath]
    return execute_error(args) or get_hashed_path(outpath)

@cache('disassembleR', temp=INVALIDATE_RS)
def disassembleR(inpath, outpath, roundtrip, no_short_code=False):
    args = ['../krakatau2/target/release/krak2', 'dis', inpath.path, '--out', outpath]
    if roundtrip:
        args.append('--roundtrip')
    if no_short_code:
        args.append('--no-short-code-attr')

    return execute_error(args) or get_hashed_path(outpath)



JREPATH = os.environ.get('JRE_PATH', '../jres/jrt9.jar')
print 'Using {} as JRE path. Set the JRE_PATH env var to change'.format(JREPATH)


@cache('decompilePy2', temp=INVALIDATE_PY)
def decompilePy2(inpath, outpath, target):
    inputdir = os.path.dirname(inpath.path)
    if not inpath.path.endswith(target + '.class'):
        # Rely on the fact that the @cache decorator always runs the wrapped function in a temporary directory with outpath located inside the tempdir
        outdir = os.path.dirname(outpath)
        new_input_path = os.path.join(outdir, target + '.class')
        shutil.copy2(inpath.path, new_input_path)
        inputdir = outdir

    args = ['python', '../Krakatau/decompile.py', '-nauto', '-path', JREPATH, '-path', inputdir, '-out', outpath, '-xaddthrows', target]
    return execute_error(args) or get_hashed_path(outpath)






JAVA_CMDS = 'java-8-oracle jdk-18'.split()
def run_java_raw(inpath, is_jar, name, jvm_ver, extra_args=[]):
    assert jvm_ver in JAVA_CMDS

    args = ['/usr/lib/jvm/{}/bin/java'.format(jvm_ver)]
    if jvm_ver == 'jdk-18':
        args.append('--enable-preview')

    dirname, fname = os.path.split(inpath)
    if is_jar:
        args += ['-cp', inpath, name]
    else:
        args += ['-cp', dirname, name]

    return execute(args + extra_args)

# Output that causes us to treat Java command as failure
ERROR_STRS = 'VerifyError ClassFormatError UnsupportedClassVersionError NoClassDefFoundError'.split()
ERROR_STRS.append('Could not find or load')
ERROR_STRS.append('Invalid or corrupt jarfile')

@cache('java')
def run_java(inpath, outpath, args):
    is_jar, name, jvm_ver, argslists = args

    if not is_jar and not inpath.path.endswith(name + '.class'):
        # Rely on the fact that the @cache decorator always runs the wrapped function in a temporary directory with inpath located inside the tempdir
        tdir = os.path.dirname(outpath)
        new_path = os.path.join(tdir, name + '.class')
        shutil.copy2(inpath.path, new_path)
        inpath = inpath._replace(path=new_path)


    results = []
    for extra_args in argslists:
        res = run_java_raw(inpath.path, is_jar, name, jvm_ver, extra_args)
        # Treat prescence of anything in ERROR_STRS as a failure
        if any(es in res.stderr for es in ERROR_STRS):
            return res
        results.append([res.stdout, res.stderr])

    json.dump(results, open(outpath, 'w'))
    return get_hashed_path(outpath)

@cache('javac')
def run_javac(inpath, outpath, jvm_ver, target):
    # Rely on the fact that the @cache decorator always runs the wrapped function in a temporary directory with outpath located inside the tempdir
    outdir = os.path.dirname(outpath)
    new_input_path = os.path.join(outdir, target + '.java')
    shutil.copy2(inpath.path, new_input_path)



    assert jvm_ver in JAVA_CMDS
    args = ['/usr/lib/jvm/{}/bin/javac'.format(jvm_ver), '-g:none', target + '.java']
    # if jvm_ver == 'jdk-18':
    #     args.append('--enable-preview')

    res = execute(args, cwd=outdir)
    # Ignore compiler unchecked warnings by looking for 'error:'
    if 'error:' in res.stderr:
        return res

    return get_hashed_path(os.path.join(outdir, target + '.class'))

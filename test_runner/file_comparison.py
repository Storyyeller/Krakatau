import shutil

from test_runner.file_util import read_zip, read
from test_runner.actions import disassemblePy2, disassembleR

class OriginDebugger(object):
    def __init__(self):
        self.d = {}
        self.counter = 1

    def display(self, hpath):
        try:
            return self.d[hpath.path]
        except KeyError:
            pass

        origin = hpath.origin
        if isinstance(origin, tuple):
            cmd = origin[0]
            inpath = origin[1]
            args = origin[2:]

            sub_name = self.display(inpath)

            ext = hpath.path.rpartition('.')[-1]
            nickname = 'file{}.{}'.format(self.counter, ext)
            self.counter += 1

            print 'Let {} by the result of {} {} {}'.format(nickname, cmd, sub_name, ' '.join(args))
            print '  {} -> {}'.format(nickname, hpath.path)
        else:
            nickname = origin
        self.d[hpath.path] = nickname
        return nickname


def compare_files(data1, data2, ext):
    if data1 != data2:
        if ext == '.class':
            with open('left.class', 'w') as f:
                f.write(data1)
            with open('right.class', 'w') as f:
                f.write(data2)


            for fname in 'left right'.split():
                path = get_hashed_path(fname + '.class')

                apath = disassemblePy2(path, '.j', roundtrip=True)
                shutil.copy2(apath.path, '{}.j'.format(fname))

                apath = disassembleR(path, '.j', roundtrip=True)
                shutil.copy2(apath.path, '{}2.j'.format(fname))
    return data1 == data2


def compare_zips(data1, data2, ext):
    members1 = read_zip(data1, ext)
    members2 = read_zip(data2, ext)

    if len(members1) != len(members2):
        print 'left {} right {} members'.format(len(members1), len(members2))
        return False
    for (n1, d1), (n2, d2) in zip(members1, members2):
        if n1 != n2:
            print u'left {!r} right {!r}'.format(n1, n2)
            return False
        if not compare_files(d1, d2, ext=ext):
            print 'mismatch in file', n1
            return False
    return True

def check_compare_binaries(apath1, apath2, input_is_zip):
    if apath1.hash != apath2.hash:
        data1 = read(apath1.path)
        data2 = read(apath2.path)
        try:
            if input_is_zip:
                assert compare_zips(data1, data2, ext='.class')
            else:
                assert compare_files(data1, data2, ext='.class')
        except AssertionError:
            print 'failed comparing', apath1.path, apath2.path

            printer = OriginDebugger()
            print 'Failed comparison between {} and {}'.format(printer.display(apath1), printer.display(apath2))
            raise

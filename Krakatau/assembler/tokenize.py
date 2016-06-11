from __future__ import print_function

import collections
import re
import sys

from . import token_regexes as res

class AsssemblerError(Exception):
    pass

Token = collections.namedtuple('Token', 'type val pos')

TOKENS = [
    ('WHITESPACE', r'[ \t]+'),
    ('WORD', res.WORD + res.FOLLOWED_BY_WHITESPACE),
    ('DIRECTIVE', res.DIRECTIVE),
    ('LABEL_DEF', res.LABEL_DEF),
    ('NEWLINES', res.NEWLINES),
    ('REF', res.REF),
    ('COLON', r':'),
    ('EQUALS', r'='),
    ('INT_LITERAL', res.INT_LITERAL + res.FOLLOWED_BY_WHITESPACE),
    ('DOUBLE_LITERAL', res.FLOAT_LITERAL),
    ('STRING_LITERAL', res.STRING_LITERAL),
    ('LEGACY_COLON_HACK', r'[0-9a-z]\w*:'),
]
REGEX = re.compile('|'.join('(?P<{}>{})'.format(*pair) for pair in TOKENS), re.VERBOSE)
# For error detection
STRING_START_REGEX = re.compile(res.STRING_START)
WORD_LIKE_REGEX = re.compile(r'\S+')

MAXLINELEN = 80

class Tokenizer(object):
    def __init__(self, source, filename):
        self.s = source
        self.pos = 0
        self.atlineend = True
        self.filename = filename.rpartition('/')[-1]

    def error(self, message, point, point2=None):
        if point2 is None:
            point2 = point + 1

        try:
            start = self.s.rindex('\n', 0, point) + 1
        except ValueError:
            start = 0
        line_start = start

        try:
            end = self.s.index('\n', start) + 1
        except ValueError:
            end = len(self.s) + 1

        # Find an 80 char section of the line around the point of interest to display
        temp = min(point2, point + MAXLINELEN//2)
        if temp < start + MAXLINELEN:
            end = min(end, start + MAXLINELEN)
        elif point >= end - MAXLINELEN:
            start = max(start, end - MAXLINELEN)
        else:
            mid = (point + temp) // 2
            start = max(start, mid - MAXLINELEN//2)
            end = min(end, start + MAXLINELEN)
        point2 = min(point2, end)

        pchars = [' '] * (end - start)
        for i in range(point - start, point2 - start):
            pchars[i] = '~'
        pchars[point - start] = '^'

        lineno = self.s[:line_start].count('\n') + 1
        colno = point - line_start + 1
        text = '{}:{}:{}: error: {}\n{}\n{}'.format(self.filename, lineno, colno,
            message, self.s[start:end].rstrip('\n'), ''.join(pchars))
        print(text, file=sys.stderr)
        raise AsssemblerError()

    def _nextsub(self):
        match = REGEX.match(self.s, self.pos)
        if match is None:
            if self.atend():
                return Token('EOF', '', self.pos)
            else:
                str_match = STRING_START_REGEX.match(self.s, self.pos)
                if str_match is not None:
                    self.error('Invalid escape sequence or character in string literal', str_match.end())

                word_match = WORD_LIKE_REGEX.match(self.s, self.pos)
                if word_match and '"' not in word_match.group() and "'" not in word_match.group():
                    self.error('Invalid token. Did you mean to use quotes?', self.pos, word_match.end())
                self.error('Invalid token', self.pos)
        assert match.start() == match.pos == self.pos

        # Hack to support invalid syntax
        if match.lastgroup == 'LEGACY_COLON_HACK':
            self.pos = match.end() - 1
            val = match.group()[:-1]
            type_ = 'INT_LITERAL' if re.match(res.INT_LITERAL, val) else 'WORD'
            return Token(type_, val, match.start())

        self.pos = match.end()
        return Token(match.lastgroup, match.group(), match.start())

    def next(self):
        tok = self._nextsub()
        while tok.type == 'WHITESPACE' or self.atlineend and tok.type == 'NEWLINES':
            tok = self._nextsub()
        self.atlineend = tok.type == 'NEWLINES'

        if tok.type == 'INT_LITERAL' and tok.val.lower().endswith('l'):
            return tok._replace(type='LONG_LITERAL')
        elif tok.type == 'DOUBLE_LITERAL' and tok.val.lower().endswith('f'):
            return tok._replace(type='FLOAT_LITERAL')
        return tok

    def atend(self): return self.pos == len(self.s)

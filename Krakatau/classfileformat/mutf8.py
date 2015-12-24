import re

NONASTRAL_REGEX = re.compile(u'[\0-\uffff]+')

def encode(s):
    assert isinstance(s, unicode)
    b = b''
    pos = 0
    while pos < len(s):
        x = ord(s[pos])
        if x >= 1<<16:
            x -= 1<<16
            high = 0xD800 + (x >> 10)
            low = 0xDC00 + (x % (1 << 10))
            b += unichr(high).encode('utf8')
            b += unichr(low).encode('utf8')
            pos += 1
        else:
            m = NONASTRAL_REGEX.match(s, pos)
            b += m.group().encode('utf8')
            pos = m.end()
    return b.replace('\0','\xc0\x80')

# Warning, decode(encode(s)) != s if s contains astral characters, as they are converted to surrogate pairs
def decode(b):
    assert isinstance(b, bytes)
    return b.replace('\xc0\x80', '\0').decode('utf8')

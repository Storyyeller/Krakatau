_pairs = [
    ('public', 0x0001),
    ('private', 0x0002),
    ('protected', 0x0004),
    ('static', 0x0008),
    ('final', 0x0010),
    ('super', 0x0020),
    ('synchronized', 0x0020),
    ('volatile', 0x0040),
    ('bridge', 0x0040),
    ('transient', 0x0080),
    ('varargs', 0x0080),
    ('native', 0x0100),
    ('interface', 0x0200),
    ('abstract', 0x0400),
    ('strict', 0x0800),
    ('synthetic', 0x1000),
    ('annotation', 0x2000),
    ('enum', 0x4000),
    ('mandated', 0x8000),
]

FLAGS = dict(_pairs)
RFLAGS_M = {v:k for k,v in _pairs}
RFLAGS = {v:k for k,v in reversed(_pairs)}
# Treat strictfp as flag too to reduce confusion
FLAGS['strictfp'] = FLAGS['strict']

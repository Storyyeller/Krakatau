import itertools

def update(self, items):
    self.nodes = frozenset.union(*(i.nodes for i in items))
    temp = set(self.nodes)
    siter = itertools.chain.from_iterable(i.successors for i in items) 
    self.successors = [n for n in siter if not n in temp and not temp.add(n)]

class SEBlockItem(object):
    def __init__(self, node):
        self.successors = node.norm_suc_nl #don't include backedges or exceptional edges
        self.node = node 
        self.nodes = frozenset([node])
    
    def getScopes(self): return ()    
    def entryBlock(self): return self.node

class SEScope(object):
    def __init__(self, items):
        self.items = items
        update(self, items)

    def getScopes(self): return ()    
    def entryBlock(self): return self.items[0].entryBlock()

class SEWhile(object):
    def __init__(self, scope):
        self.body = scope
        self.nodes = scope.nodes
        self.successors = scope.successors

    def getScopes(self): return self.body,    
    def entryBlock(self): return self.body.entryBlock()

class SETry(object):
    def __init__(self, tryscope, catchscope, toptts, catchvar):
        self.scopes = tryscope, catchscope
        self.toptts = toptts
        self.catchvar = catchvar #none if ignored
        update(self, self.scopes)

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.scopes[0].entryBlock()

class SEIf(object):
    def __init__(self, head, newscopes):
        assert(len(newscopes) == 2)
        self.scopes = newscopes
        self.head = head
        update(self, [head] + newscopes)

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.head.entryBlock()

class SESwitch(object):
    def __init__(self, head, newscopes):
        self.scopes = newscopes
        self.head = head
        self.ordered = newscopes
        update(self, [head] + newscopes)

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.head.entryBlock()

import itertools, collections

from ..ssa import ssa_jumps #needed to detect ifs and switches
from .. import graph_util
from . import ast, preprocess

def replaceSELinks(items, new):
    iset = set(items)
    entrypoints = set()
    for item in items:
        for source in item.sources[:]:
            if source not in iset:
                source.successors.remove(item)
                if new not in source.successors:
                    source.successors.append(new)
                    new.sources.append(source)
                item.sources.remove(source)
                entrypoints.add(item)
    for item in items:
        for child in item.successors[:]:
            if child not in iset:
                child.sources.remove(item)
                if new not in child.sources:
                    child.sources.append(new)
                    new.successors.append(child)
                item.successors.remove(child)
    assert(len(entrypoints) <= 1)

def linkCheck(items):
    for item in items:
        for source in item.sources:
            assert(item in source.successors)
        for child in item.successors:
            assert(item in child.sources)

class SEBlockItem(object):
    def __init__(self, block):
        self.sources, self.successors = [], []
        self.block = block 
        self.blocks = frozenset([block])
    
    def getScopes(self): return ()    
    def entryBlock(self): return self.block
    def __str__(self): return str(self.block)
    __repr__ = __str__

class SEScope(object):
    def __init__(self, items, head, isTopScope=False):
        assert(head in items)
        self.sources, self.successors = [], []
        self.items = items
        self.head = head
        self.blocks = frozenset.union(*(i.blocks for i in items))
        if not isTopScope:
            replaceSELinks(items, self)

    def getScopes(self): return ()    
    def entryBlock(self): return self.head.entryBlock()

class SEWhile(object):
    def __init__(self, scope):
        self.sources, self.successors = [], []
        self.body = scope
        self.blocks = scope.blocks
        replaceSELinks([scope], self)

        #remove backedges
        backs = scope.head.sources
        assert(backs)
        for item in backs:
            item.successors.remove(scope.head)
        scope.head.sources = ()

    def getScopes(self): return self.body,    
    def entryBlock(self): return self.body.entryBlock()

class SETry(object):
    def __init__(self, tryscope, decl, catchscope):
        self.sources, self.successors = [], []
        self.scopes = tryscope, catchscope
        self.blocks = frozenset.union(*(i.blocks for i in self.scopes))
        self.decl = decl

        #Since try blocks are created before while nodes, we must preserve self reference information
        if tryscope in (tryscope.successors + catchscope.successors):
            self.sources.append(self)
            self.successors.append(self)
        replaceSELinks(self.scopes, self)

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.scopes[0].entryBlock()

class SEIf(object):
    def __init__(self, head, newscopes):
        self.sources, self.successors = [], []
        self.scopes = newscopes
        self.head = head

        assert(1 <= len(newscopes) <= 2)
        items = [head] + newscopes 
        self.blocks = frozenset.union(*(i.blocks for i in items))
        replaceSELinks(items, self)

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.head.entryBlock()
    def __str__(self): return 'IF'+str(self.entryBlock())[2:]
    __repr__ = __str__

class SESwitch(object):
    def __init__(self, head, newscopes, orders, criticalEdges):
        self.sources, self.successors = [], []
        self.critical = criticalEdges
        self.scopes = newscopes
        self.head = head
        self.orders = orders

        items = [head] + newscopes
        self.blocks = frozenset.union(*(i.blocks for i in items))
        replaceSELinks(items, self)
        assert(set(i.entryBlock() for i in self.scopes).issuperset(criticalEdges))

    def getScopes(self): return self.scopes
    def entryBlock(self): return self.head.entryBlock()

def _createWhileNodes(scope):
    while True:
        sccs = graph_util.tarjanSCC(scope.items, lambda item:item.sources)
        #be careful, we can also have selfloops due to the prior creation of try blocks
        loops = [scc for scc in sccs if (len(scc)>1) or (scc[0] in scc[0].sources)]
        if not loops:
            break

        scc = loops[-1]
        #Try to expand the while node until it has only one exit
        current = list(scc)
        best = scc, len(scope.items)
        while best[1]>1:
            successors = itertools.chain.from_iterable(item.successors for item in current)
            temp = set(current) #set.add abuse to quickly eliminate duplicates
            frontier = [x for x in successors if not x in temp and not temp.add(x)]
            if len(frontier) <= best[1]:
                best = current, len(frontier)

            for c in frontier:
                #Make sure the item we're trying to expand with isn't reachable from outside
                if any(x != c and x not in current for x in c.sources):
                    continue
                current.append(c)
                break
            else:
                break           
        chosen = best[0]

        if scope.head in scc:
            head = scope.head
        else:
            heads = [item for item in scc if not set(scc).issuperset(item.sources)]
            assert(len(heads) == 1)
            head = heads[0]

        new = SEScope(chosen, head)
        wnode = SEWhile(new)

        scope.items = [x for x in scope.items if x not in chosen] + [wnode]
        if scope.head in chosen:
            scope.head = wnode
    #Now we've created all the loops possible on this level, recurse
    for item in scope.items:
        if isinstance(item, SEScope):
            _createWhileNodes(item)
        else:
            for sub in item.getScopes():
                _createWhileNodes(sub)

def _getCaughtVar(data, hitem, tt):
    block = hitem.entryBlock()
    candidates = []
    for phi in block.phis:
        if all(var.origin and (var == var.origin.outException) for var in phi.odict.values()):
            candidates.append(phi.rval)
    assert(len(candidates) <= 1)
    if candidates:
        local = data.varinfo[candidates[0]].expr
        return local 
    return ast.Local(tt, lambda expr:data.namegen.getPrefix('ignoredException'))

def _createTryNode(data, scope, hInfo):
    handler = hInfo.handler
    subscopes = (([item] if isinstance(item, SEScope) else item.getScopes()) for item in scope.items)
    for item in itertools.chain(*subscopes):
        if item.blocks.issuperset(hInfo.blocks) and handler in item.blocks:
            return _createTryNode(data, item, hInfo)
    del subscopes #prevent accidental use later

    tryitems = [item for item in scope.items if (hInfo.blocks & item.blocks)]
    catchitems = [item for item in scope.items if handler in item.blocks]
    assert(len(catchitems) == 1 and catchitems[0] not in tryitems)
    catchhead = catchitems[0]

    # Attempt to expand try and catch blocks in order to reduce the number of successors. We have to use dominators instead
    # of normal reachability because while blocks have not been created yet
    dominators = preprocess.getDominators(scope.head, lambda item:item.successors)
    predom = preprocess.commonDominator(dominators, tryitems+catchitems)
    assert(predom in tryitems)

    # Post dominators requires a hack because there is not necessarilly a common descendant. We create a dummy object to 
    # serve as the root which has as its sources every node which doesn't progress forwards. Note that this includes 
    # not only nodes with no successors, but also nodes in an infinite loop, in which case we choose an arbitrary node from
    # the loop to serve as the 'end' of the loop
    tsorted = graph_util.topologicalSort(scope.items, lambda item:item.sources)
    terminals = [x for i,x in enumerate(tsorted) if all(tsorted.index(item) <= i for item in x.successors)]
    postroot = type('_postroot_t',(object,),{'sources':terminals})
    postdominators = preprocess.getDominators(postroot, lambda item:item.sources)

    postdom = preprocess.commonDominator(postdominators, tryitems + catchitems)
    tryreach = graph_util.topologicalSort(tryitems, lambda item:[x for x in item.successors if x not in catchitems and x != postdom])
    catchreach = graph_util.topologicalSort(catchitems, lambda item:[x for x in item.successors if x != predom and x != postdom])
    assert(not(set(tryitems) & set(catchreach)))
    common = [x for x in tryreach if x in catchreach]
    tryreach = [x for x in tryreach if x not in common]
    catchreach = [x for x in catchreach if x not in common]

    def expandBlock(initial, forbidden, forCatch):
        current = initial
        best = initial, len(scope.items)
        goal = postdom if postdom != postroot else preprocess.commonDominator(postdominators, initial)
        while 1:
            successors = itertools.chain.from_iterable(item.successors for item in current)
            temp = set(current) #set.add abuse to quickly eliminate duplicates
            frontier = [x for x in successors if not x in temp and not temp.add(x)]
            if len(frontier) <= best[1]:
                best = current, len(frontier)

            candidates = [x for x in frontier if x not in forbidden and x != goal]
            for c in candidates:
                #Make sure the item we're trying to expand with isn't reachable from outside
                if any(x != c and x not in current for x in c.sources):
                    continue
                for block in c.blocks:
                    if not hInfo.extend(block, forCatch=forCatch):
                        break 
                else:
                    current.append(c)
                    break
            else:
                break
        return current

    tryitems = expandBlock(tryitems, set(common + catchitems), False)
    catchitems = expandBlock(catchitems, set(common + tryitems), True)
    #make sure the regions are still disjoint
    combined = tryitems + catchitems + common
    assert(len(set(combined)) == len(combined))
    ########################################################################################################################
    caught_tt = hInfo.catch_tt
    caught_expr = _getCaughtVar(data, catchitems[0], caught_tt)
    caught_decl = ast.VariableDeclarator(ast.TypeName(caught_tt), caught_expr)

    tryblock = SEScope(tryitems, predom)
    catchblock = SEScope(catchitems, catchhead)
    tnode = SETry(tryblock, caught_decl, catchblock)

    removed = set().union(tryitems, catchitems)
    scope.items = [i for i in scope.items if i not in removed]
    scope.items.append(tnode)
    if scope.head in removed:
        scope.head = tnode
    assert(scope.head in scope.items)

def _splitOffScope(scope, choices):
    reverse = graph_util.topologicalSort(choices, lambda item:item.successors)
    #We wish to find a child which cannot reach any other child. Therefore, we pick the one with
    #smallest index in a reverse topological sorting
    end = min(choices, key=reverse.index)
    dominators = preprocess.getDominators(scope.head, lambda item:item.successors)
    start = preprocess.commonDominator(dominators, end.sources)

    afterScope = graph_util.topologicalSort([end], lambda item:item.successors)
    covered = graph_util.topologicalSort([start], lambda item:[x for x in item.successors if x not in afterScope])
    while preprocess.commonDominator(dominators, covered) != start:
        start = preprocess.commonDominator(dominators, covered)
        covered = graph_util.topologicalSort([start], lambda item:[x for x in item.successors if x not in afterScope])

    if start == scope.head:
        beforeScope = []
    else:
        beforeScope = graph_util.topologicalSort([scope.head], lambda item:[x for x in item.successors if x != start and x not in afterScope])
    assert(sorted(beforeScope + covered + afterScope) == sorted(scope.items))

    new = SEScope(covered, start)
    newitems = beforeScope + [new] + afterScope
    scope.items = newitems
    if scope.head in covered:
        scope.head = new
    assert(scope.head in scope.items)
    linkCheck(scope.items)

def _createSwitchNodeSub(scope, parent):
    jump = parent.block.jump
    reverse = graph_util.topologicalSort([parent], lambda item:item.successors)
    #ensure children are in reverse topo order
    children = sorted(parent.successors, key=reverse.index)
    reaches = {child:graph_util.topologicalSort([child], lambda item:item.successors) for child in children}     

    pruned = {}
    heads = []
    followers = {}

    for child in children:
        fts = [h for h in heads if h in reaches[child]]
        if len(fts) > 1: #impossible to create switch here
            return

        if fts:
            fallthrough = fts[0]
            heads.remove(fallthrough)
            followers[child] = fallthrough
            pruned[child] = graph_util.topologicalSort([child], lambda item:[x for x in item.successors if x != fallthrough])
            assert(fallthrough not in pruned[child])
        else:
            pruned[child] = reaches[child]
        heads.append(child)

    #Now get lists of blocks that must be consecutive due to fallthrough. 
    orders = []
    for head in heads:
        curlist = []
        curlist.append(head.entryBlock())
        while head in followers:
            head = followers[head]
            curlist.append(head.entryBlock())
        orders.append(curlist)

    #Find blocks in two or more of the bodies and remove them
    counts = collections.Counter(itertools.chain.from_iterable(pruned.values()))
    common = set(x for x in reverse if counts[x] >= 2)

    if not common.isdisjoint(children):
        return

    #unordered
    cheads = [x for x in common if not common.issuperset(x.sources)]
    if len(cheads) <= 1:
        #make new switch block
        newscopes = []
        for child in children:
            body = [x for x in pruned[child] if x not in common]
            newscope = SEScope(body, child)
            if len(body) > 1: #if the extra scope is actually unecessary, hopefully we can remove it in post processing
                newscope = SEScope([newscope], newscope)
            newscopes.append(newscope)

        critical = frozenset(i.entryBlock() for i in followers.values())
        newnode = SESwitch(parent, newscopes, orders, critical)
        removed = set([parent]).union(*pruned.values()) - common
        scope.items = [i for i in scope.items if i not in removed]
        scope.items.append(newnode)
        if scope.head in removed:
            scope.head = newnode
        return newnode

def _createIfNodeSub(scope, todo):
    for parent in todo:
        if not isinstance(parent, SEBlockItem):
            _splitOffScope(scope, parent.successors)
            return         
    #topologically sort the remaining nodes
    temp = graph_util.topologicalSort(todo, lambda item:item.sources)
    parent = min(todo, key=temp.index)

    assert(isinstance(parent, SEBlockItem))
    if isinstance(parent.block.jump, ssa_jumps.If):
        #check if parent is valid head of an if block and if so, create one
        children = parent.successors
        reaches = [graph_util.topologicalSort([child], lambda item:item.successors) for child in children]
        common = set(reaches[0]).intersection(*reaches[1:])
        #unordered
        cheads = [x for x in common if not common.issuperset(x.sources)]

        if len(cheads) <= 1:
            bodies = [[x for x in reach if x not in common] for reach in reaches]
            scopes = [SEScope(body, child) for body, child in zip(bodies, children) if body]
            assert(scopes)
            ifnode = SEIf(parent, scopes)

            removed = set([parent]).union(*bodies)
            scope.items = [i for i in scope.items if i not in removed]
            scope.items.append(ifnode)
            if scope.head in removed:
                scope.head = ifnode
            return             
        else:
            _splitOffScope(scope, cheads)
            return        
    elif isinstance(parent.block.jump, ssa_jumps.Switch):
        #check if parent is valid head of an if block and if so, create one
        if _createSwitchNodeSub(scope, parent) is not None:
            return
        # else:
        #     print 'Switch creation failed!'
    #no if blocks can be made so just split everything anyway
    # parent = max(todo, key=temp.index)
    _splitOffScope(scope, parent.successors)      

def _createIfNodes(scope):
    while 1:
        todo = [item for item in scope.items if len(item.successors) > 1]
        if not todo:
            break
        assert(len(scope.items) > 2)
        _createIfNodeSub(scope, todo)
    #Make sure the remaining items are in linear order
    assert(scope.head in scope.items)

    cur = scope.head 
    newitems = [cur]
    while cur.successors:
        cur = cur.successors[0]
        newitems.append(cur)
    scope.items = newitems

    for item in scope.items:
        for subscope in item.getScopes():
            _createIfNodes(subscope)
        if isinstance(item, SEScope):
            _createIfNodes(item)
    assert(scope.items[0] == scope.head)

def createSETree(data, blocks, entryBlock, handlerInfos):
    items = map(SEBlockItem, blocks)
    iMap = {item.block:item for item in items}
    head = iMap[entryBlock]

    for item in items:
        children = item.block.getSuccessors()
        item.successors = map(iMap.get, children)
        for child in item.successors:
            child.sources.append(item)
    assert(not head.sources)

    def checkUnique(seq): 
        assert(len(set(seq)) == len(seq))    
    for item in items:
        checkUnique(item.sources)
        checkUnique(item.successors)

    root = SEScope(items, head, isTopScope=True)
    assert(root.blocks == frozenset(blocks))
    # import pdb;pdb.set_trace()

    for hInfo in handlerInfos:
        _createTryNode(data, root, hInfo)
    _createWhileNodes(root)
    _createIfNodes(root)
    return root
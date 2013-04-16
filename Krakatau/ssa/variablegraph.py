import collections, itertools

from constraints import join, meet
from .. import graph_util
#UC = unary constraints

class BaseNode(object):
    def __init__(self, processfunc, isphi):
        assert(processfunc is not None)
        self.sources = []
        self.uses = []
        self.process = processfunc
        self.itercount = 0
        self.propagateInvalid = not isphi
        #self.output to be filled in

        self.root = None #for debugging purposes, store the SSA object this node corresponds to

    def update(self):
        if not self.sources:
            return False

        inputs = [node.output[key] for node,key in self.sources]
        if self.propagateInvalid and None in inputs:
            new = [None]*len(self.output)
        else:
            inputs = [x for x in inputs if x is not None]
            new = self.process(*inputs)
            new = [(None if newv is None else join(oldv, newv)) for oldv, newv in zip(self.output, new)]

        if new != self.output:
            self.output = new
            self.itercount += 1
            return True
        return False

    # def mark(self):
    #     return str(self.root).startswith('i')

def registerUses(use, sources):
    for node,index in sources:
        node.uses.append(use)

def getJumpNode(pair, source, outvar, getVarNode, jumplookup):
    if (source, pair, outvar) in jumplookup:
        return jumplookup[(source, pair, outvar)]
    jump = source.jump
    #OnException may still have a valid successor even if the param is invalid
    # skipInvalid = isinstance(jump, ssa_jumps.OnException)
    skipInvalid = False
    n = BaseNode(jump.getSuccessorConstraints(pair), skipInvalid)

    n.sources = [(getVarNode(var),0) for var in jump.params]
    registerUses(n, n.sources)

    n.output = [t[0].output[0] for t in n.sources]
    n.root = jump

    for i,var in enumerate(jump.params):
        jumplookup[(source, pair, var)] = n, i
    return jumplookup[(source, pair, outvar)]

def makeGraph(env, blocks):
    lookup = collections.OrderedDict()
    jumplookup = {}

    variables = itertools.chain.from_iterable(block.unaryConstraints.items() for block in blocks)
    phis = itertools.chain.from_iterable(block.phis for block in blocks)
    ops = itertools.chain.from_iterable(block.lines for block in blocks)

    #We'll be using these a lot so might as well just store one copy
    varlamb = lambda *x:x
    philamb = lambda *x:[meet(*x) if x else None]

    for var, curUC in variables:
        n = BaseNode(varlamb, False)
        #sources and uses will be reassigned upon opnode creation
        n.output = [curUC]
        lookup[var] = n
        # n.root = var

    for phi in phis:
        n = BaseNode(philamb, True)
        block = phi.block

        for (source, exc), var in phi.odict.items():
            if var in source.jump.params and hasattr(source.jump, 'getSuccessorConstraints'):
                jump, index = getJumpNode((block, exc), source, var, lookup.get, jumplookup)
                n.sources.append((jump, index))
            else:
                n.sources.append((lookup[var],0))
        registerUses(n, n.sources)

        outnode = lookup[phi.rval]
        n.output = [outnode.output[0]]
        outnode.sources = [(n,0)]
        n.uses.append(outnode)
        n.root = phi

    for op in ops:
        if hasattr(op, 'propagateConstraints'):
            n = BaseNode(op.propagateConstraints, False)
            n.sources = [(lookup[var],0) for var in op.params]
            registerUses(n, n.sources)
        else:
            #Quick hack - if no processing function is defined, just leave sources empty so it will never be updated
            n = BaseNode(42, False)
        n.output = []
        for i,var in enumerate(op.getOutputs()):
            vnode = lookup[var]
            n.output.append(vnode.output[0])
            n.uses.append(vnode)
            vnode.sources = [(n,i)]
        n.root = op

    #sanity check
    vnodes = lookup.values() 
    for node in vnodes:
        if node.sources:
            for source in zip(*node.sources)[0]:
                assert(node in source.uses)
        for use in node.uses:
            assert(node in zip(*use.sources)[0])

    return lookup

def processGraph(graph, iterlimit=5):
    sccs = graph_util.tarjanSCC(graph.values(), lambda node:[t[0] for t in node.sources])
    #iterate over sccs in topological order to improve convergence

    for scc in sccs:
        worklist = list(scc)
        while worklist:
            node = worklist.pop(0)
            if node.itercount < iterlimit:
                changed = node.update()
                if changed:
                    worklist.extend(use for use in node.uses if use in scc and use not in worklist)
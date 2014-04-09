import collections, itertools

from .constraints import join, meet
from .. import graph_util
#UC = unary constraints

class BaseNode(object):
    def __init__(self, processfunc, isphi, filterNone=True):
        assert(processfunc is not None)
        self.sources = []
        self.uses = []
        self.process = processfunc
        self.iters = 0
        self.propagateInvalid = not isphi
        self.filterNone = filterNone
        self.output = None #to be filled in later
        self.lastInput = []

        self.root = None #for debugging purposes, store the SSA object this node corresponds to

    def _propagate(self, inputs):
        if self.propagateInvalid and None in inputs:
            new = (None,)*len(self.output)
        else:
            if self.filterNone:
                inputs = [x for x in inputs if x is not None]
            new = self.process(*inputs)
            assert(len(self.output)==len(new))
            new = tuple(join(oldv, newv) for oldv, newv in zip(self.output, new))
        return new

    def update(self, iterlimit):
        if not self.sources:
            return False

        changed = False
        if self.iters < iterlimit:
            old, self.lastInput = self.lastInput, [node.output[key] for node,key in self.sources]
            if old != self.lastInput:
                new = self._propagate(self.lastInput)
                if new != self.output:
                    self.output = new
                    self.iters += 1
                    changed = True
        return changed

def registerUses(use, sources):
    for node,index in sources:
        node.uses.append(use)

def getJumpNode(pair, source, var, getVarNode, jumplookup):
    if (source, pair, var) in jumplookup:
        return jumplookup[(source, pair, var)]

    jump = source.jump
    if var in jump.params:
        if hasattr(jump, 'getSuccessorConstraints'):
            n = BaseNode(jump.getSuccessorConstraints(pair), False)
            n.sources = [(getVarNode(param),0) for param in jump.params]
            registerUses(n, n.sources)

            n.output = tuple(t[0].output[0] for t in n.sources)
            n.root = jump

            for i, param in enumerate(jump.params):
                jumplookup[(source, pair, param)] = n, i
            return jumplookup[(source, pair, var)]

    return getVarNode(var), 0

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
        n.output = (curUC,)
        lookup[var] = n
        n.root = var

    for phi in phis:
        n = BaseNode(philamb, True)
        block = phi.block
        for (source, exc) in block.predecessors:
            n.sources.append(getJumpNode((block, exc), source, phi.get((source, exc)), lookup.get, jumplookup))
        registerUses(n, n.sources)

        outnode = lookup[phi.rval]
        n.output = (outnode.output[0],)
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
        output = []
        for i,var in enumerate(op.getOutputs()):
            if var is None:
                output.append(None)
            else:
                vnode = lookup[var]
                output.append(vnode.output[0])
                n.uses.append(vnode)
                vnode.sources = [(n,i)]
        n.output = tuple(output)
        n.root = op
        assert(len(output) == 3)

    vnodes = lookup.values()

    #sanity check
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
        scc_s = set(scc)

        while worklist:
            node = worklist.pop(0)
            changed = node.update(iterlimit)
            if changed:
                worklist.extend(use for use in node.uses if use in scc_s and use not in worklist)

from ..ssa import ssa_ops, ssa_jumps, ssa_types, constraints, objtypes

def pruneExceptions(block, func=(lambda j:j.constrainJumps(None))):
    oldEdges = block.jump.getSuccessorPairs()

    func(block.jump)
    block.jump = block.jump.reduceSuccessors([])

    newEdges = block.jump.getSuccessorPairs()
    pruned = [x for x in oldEdges if x not in newEdges]
    for (child,t) in pruned:
        child.removePredPair((block, t))

def makeOpConstant(graph, block, op, val):
    assert(op in block.lines and op.rval is not None)
    block.lines.remove(op)

    if op.outException is not None:
        evar = op.outException
        jump = block.jump
        assert(isinstance(jump, ssa_jumps.OnException))
        assert(jump.params[0] == evar)

        pruneExceptions(block)
        del block.unaryConstraints[op.outException]
        op.outException = None

    if op.outMonad is not None:
        new = op.params[0]
        assert(op.outMonad.type == new.type == ssa_types.SSA_MONAD)

        replace = {op.outMonad:new}
        for op2 in block.lines:
            op2.replaceVars(replace)
        for b2 in block.jump.getSuccessors():
            for phi in b2.phis:
                phi.replaceVars(replace)

        del block.unaryConstraints[op.outMonad]
        op.outMonad = None

    rval = op.rval
    if rval.type[0] == ssa_types.SSA_INT[0]:
        con = constraints.IntConstraint.const(rval.type[1], val)
    else:
        assert(isinstance(val, basestring))
        val = unicode(val)
        con = constraints.ObjectConstraint.fromTops(graph.env, [], [objtypes.StringTT], nonnull=True)

    assert(constraints.join(con, block.unaryConstraints[rval]) == con)
    block.unaryConstraints[rval] = con
    rval.origin = None
    rval.const = val

def doDecrypt(decrypt, op, block, graph):
    if decrypt is None:
        return
    arg = op.params[-1]
    pblock = block
    while arg.const is None:
        if arg.origin not in pblock.phis or len(pblock.predecessors) != 1:
            return
        phi = [p for p in pblock.phis if p.rval is arg][0]
        assert(len(phi.dict) == 1)
        pred, arg = phi.dict.items()[0]
        pblock = pred[0]
    assert(arg.const is not None)
    assert(arg.decltype == objtypes.StringTT)

    cipher = arg.const
    clear = decrypt(cipher, graph=graph)
    makeOpConstant(graph, block, op, clear)

def constStringFilter(decrypt_factory):
    def filterStrings(graph, infos, **kwargs):
        for block in graph.blocks:
            for op in block.lines:
                if not isinstance(op, ssa_ops.Invoke):
                    continue
                if op.desc != '(Ljava/lang/String;)Ljava/lang/String;':
                    continue
                decrypt = decrypt_factory(graph, op, infos)
                doDecrypt(decrypt, op, block, graph)
        graph.mergeSingleSuccessorBlocks()
        graph.removeUnusedVariables()
    return filterStrings
import collections

from .setree import SEBlockItem, SEScope, SEIf, SESwitch, SETry, SEWhile
from .. import graph_util
from ..ssa import ssa_ops, ssa_jumps

def visitItem(current, nodes, cdict, catches=()):
    if isinstance(current, SEBlockItem):
        node = current.node
        nodes.append(node)
        for cs in catches:
            cs.add(node)
    elif isinstance(current, SEScope):
        for item in current.items:
            visitItem(item, nodes, cdict, catches)
    elif isinstance(current, SETry):
        visitItem(current.scopes[0], nodes, cdict, catches)
        if current.catchvar is not None:
            cvar = current.scopes[1].entryBlock, current.catchvar, False
            catches += cdict[cvar],
        visitItem(current.scopes[1], nodes, cdict, catches)
    else:
        if isinstance(current, (SEIf, SESwitch)):
            visitItem(current.head, nodes, cdict, catches)
        for scope in current.getScopes():
            visitItem(scope, nodes, cdict, catches)

def mergeVariables(setree):
    nodes = []    
    catch_regions = collections.defaultdict(set)
    visitItem(setree, nodes, catch_regions)

    assigns = collections.defaultdict(set)
    for node in nodes:
        block = node.block
        cast_repl = {}
        if block is not None and block.lines:
            if isinstance(block.lines[-1], ssa_ops.CheckCast) and isinstance(block.jump, ssa_jumps.OnException):
                var = block.lines[-1].params[0]
                cast_repl[node, var, False] = node, var, True

        for n2 in node.successors:
            assert((n2 in node.outvars) != (n2 in node.eassigns))
            if n2 in node.eassigns:
                for outv, inv in zip(node.eassigns[n2], n2.invars):
                    if outv is None: #this is how we mark the thrown exception, which 
                        #obviously doesn't get an explicit assignment statement
                        continue
                    assigns[n2, inv, False].add((node, outv, False))
            else:
                for outv, inv in zip(node.outvars[n2], n2.invars):
                    key = node, outv, False
                    assigns[n2, inv, False].add(cast_repl.get(key,key))

    #Handle use of caught exception outside its defining scope   
    roots = {} 
    for k, defs in assigns.items():
        for v in defs:
            if v in catch_regions and k[0] not in catch_regions[v]:
                roots[k] = k
                break

    while 1:
        #Note this is nondeterministic
        remain = [v for v in assigns if v not in roots]
        sccs = graph_util.tarjanSCC(remain, lambda svar:[v for v in assigns[svar] if v not in roots])
        for scc in sccs:
            defs = set().union(*(assigns[svar] for svar in scc))
            defs -= set(scc)

            if not defs:
                assert(len(scc)==1)
                roots[scc[0]] = scc[0]
            else:
                defroots = set(roots[x] for x in defs)
                if len(defroots) == 1:
                    root = defroots.pop()
                    for svar in scc: 
                        roots[svar] = root                       
                else:
                    for svar in scc: 
                        if not assigns[svar].issubset(scc):
                            roots[svar] = svar
                    break #we have new roots, so restart the loop
        else: #iterated through all sccs without a break so we're done
            break  

    for k,v in roots.items():
        if k is not v:
            assert(isinstance(k[1].origin, ssa_ops.Phi))
    return roots
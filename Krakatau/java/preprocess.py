import collections, itertools
import copy
ODict = collections.OrderedDict

from ..ssa import ssa_types, ssa_ops, ssa_jumps
from ..ssa import objtypes, constraints, exceptionset
from ..graph_util import topologicalSort, tarjanSCC

class DecompilationError(Exception):
    def __init__(self, message, data=None):
        super(DecompilationError, self).__init__(message)
        self.data = data

def error(msg):
    raise DecompilationError(msg)


def getLast(seq):
    return seq[-1] if seq else None

_ssaToTT = {ssa_types.SSA_INT:'.int', ssa_types.SSA_LONG:'.long',
            ssa_types.SSA_FLOAT:'.float', ssa_types.SSA_DOUBLE:'.double'}
def getVarType(var, uc):
    if var.type == ssa_types.SSA_OBJECT:
        tt = uc.getSingleTType()
        if tt[1] == objtypes.ObjectTT[1] and uc.types.isBoolOrByteArray():
            return '.bexpr', tt[1]+1
        return tt
    else:
        return _ssaToTT[var.type], 0   

class VariableInfo(object):
     def __init__(self, var):
        self.var = var
        self.uc = self.expr = None

class BlockProxy(object):
    def __init__(self, key):
        self.key = str(key)
        self.phis = []
        self.lines = []
        self.UCs = None #ODict()
        self.counter = itertools.count(1) #for naming blocks duplicated from this
        # self.jump = copy.copy(block.jump)
        # self.catchset = exceptionset.CatchSetManager(env, self.jump.handlers)

    def getNormalSuccessors(self): return self.jump.getNormalSuccessors()
    def getExceptSuccessors(self): return self.jump.getExceptSuccessors()
    def getSuccessors(self): return self.jump.getSuccessors()
    def getSuccessorPairs(self): return self.jump.getSuccessorPairs()

    def replaceBlock(self, block, t, newb):
        if t:
            assert(block in self.jump.getExceptSuccessors())
            self.jump.replaceExceptTarget(block, newb)
            self.catchset.replaceKey(block, newb)
        else:
            assert(block in self.jump.getNormalSuccessors())
            #Most jumps don't bother to define seperate replace normal and excepts since they have no exception successors anyway
            if self.jump.getExceptSuccessors():
                self.jump.replaceNormalTarget(block, newb)
            else:
                self.jump.replaceBlocks({block:newb})

    def __str__(self): return 'PB' + self.key
    def __repr__(self): return 'PB' + self.key

def makeGraphCopy(env, graph):
    assert(not graph.procs)
    varucs = ODict()
    varreplace = ODict()
    varorigins = collections.defaultdict(list)
    variable_iter = itertools.chain.from_iterable(block.unaryConstraints.items() for block in graph.blocks)
    
    for var, uc in variable_iter:
        assert(var not in varreplace)
        new = copy.copy(var)
        varreplace[var] = new 
        varorigins[new.origin].append(new)
        #store the uc for later
        varucs[new] = uc 

    def makeNewOp(old):
        new = old.clone() if hasattr(old,'clone') else copy.copy(old)
        for var in varorigins[old]:
            var.origin = new 
        new.replaceVars(varreplace)
        if isinstance(new, ssa_ops.BaseOp):
            new.replaceOutVars(varreplace)
        return new

    blockMap = {}
    blocks = []

    for old in graph.blocks:
        block = BlockProxy(old.key)
        block.phis = map(makeNewOp, old.phis)
        block.lines = map(makeNewOp, old.lines)
        block.jump = makeNewOp(old.jump)

        newvars = map(varreplace.get, old.unaryConstraints.keys())
        block.UCs = ODict((var,varucs[var]) for var in newvars)
        
        blockMap[old] = block 
        blocks.append(block)
    
    for block in blocks:
        block.jump.replaceBlocks(blockMap)
        for phi in block.phis:
            phi.replaceBlocks(blockMap)

        if isinstance(block.jump, ssa_jumps.OnException):
            block.catchset = block.jump.cs.copy()
        else:
            block.catchset = None

    # import pdb;pdb.set_trace()
    argvars = [varreplace[var] for var in graph.inputArgs[1:] if var is not None]
    return blocks, argvars
    # return blocks, map(varreplace.get, graph.inputArgs[1:])

def addDecInfo(env, blocks):
    varinfo = ODict()
    for block in blocks:
        for var, uc in block.UCs.items():
            varinfo[var] = info = VariableInfo(var)
            info.uc = uc
            if var.type != ssa_types.SSA_MONAD:
                info.atype = getVarType(var, uc)
        del block.UCs
    return varinfo

##############################################################################################################
def getDominators(root, getChildren=BlockProxy.getSuccessors):
    doms = {root:(root,)}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in getChildren(cur):
            new = doms[cur] + (child,)
            old = doms.get(child)
            if new != old: #todo - figure out how to do this properly
                new = new if old is None else tuple(x for x in old if x in new)
                assert(child in new)
            if new != old:
                doms[child] = new
                if child not in stack:
                    stack.append(child)
    return doms

def commonDominator(dominators, kernel):
    return [x for x in zip(*map(dominators.get, kernel)) if len(set(x))==1][-1][0]

##############################################################################################################

def getSources(blocks, root):
    esources, nsources = collections.defaultdict(list), collections.defaultdict(list)
    for block in blocks:
        for child in block.getNormalSuccessors():
            nsources[child].append(block)
        for child in block.getExceptSuccessors():
            esources[child].append(block)        
    nsources[root] = []
    sources = {k:nsources[k]+esources[k] for k in blocks}
    assert(not sources[root])
    return sources, nsources, esources    

def getNewBlockName(block, suffix):
    i = block.counter.next()
    val = block.key + suffix
    if i>1:
        val += str(i)
    return val

def indirectBlock(block, inedges):
    assert(inedges)
    newb = BlockProxy(getNewBlockName(block, '?'))
    newb.UCs = ODict()

    for source, t in inedges:
        source.replaceBlock(block, t, newb)

    for phi in block.phis:
        pairs1 = [(k,v) for k,v in phi.odict.items() if k in inedges]
        pairs2 = [(k,v) for k,v in phi.odict.items() if k not in inedges]

        newvar = copy.copy(phi.rval)
        newb.UCs[newvar] = block.UCs[phi.rval]

        newphi = ssa_ops.Phi(None, pairs1, newvar)
        newvar.origin = newphi
        newb.phis.append(newphi)

        pairs2.append(((newb, False), newvar))
        phi.updateDict(pairs2)
    newb.jump = ssa_jumps.Goto(None, block)
    newb.catchset = None #only has one if jump is onexception
    return newb 

def makeGraphSimple(blocks, root):
    #Make sure graph is a simple digraph to simplify things later
    newblocks = []

    for block in blocks:
        if block in block.getExceptSuccessors():
            newblocks.append(indirectBlock(block, [(block, True)]))
        if block in block.getNormalSuccessors():
            newblocks.append(indirectBlock(block, [(block, False)]))

    sources, nsources, esources = getSources(blocks, root)
    for block in blocks:
        assert(block not in sources[block])
        if nsources[block] and esources[block]:
            ein = [(x, True) for x in esources[block]]
            new = indirectBlock(block, ein)
            newblocks.append(new)
    return newblocks

def fixSCCHeads(blocks, root):
    newblocks = []
    blocks = list(blocks)
    #assert everything reachable from root

    sources, nsources, esources = getSources(blocks, root)
    sccs = tarjanSCC(blocks, sources.get)
    while sccs:
        scc = sccs.pop()
        assert(scc not in sccs)
        if len(scc) < 2:
            continue

        oin = [(block, [x for x in sources[block] if x not in scc]) for block in scc]
        oin = ODict((k,v) for k,v in oin if v)
        assert(oin)
        if len(oin)>1: #choose head
            candidates = oin.keys()
            min_ein = min(len(esources[x]) for x in candidates)
            candidates = [x for x in candidates if len(esources[x]) <= min_ein]
            head = candidates[0]
        else:
            head = oin.keys()[0]

        seeds = [x for x in oin if x != head]
        if seeds:
            #reachable
            target = topologicalSort(seeds, lambda block:[x for x in block.getSuccessors() if x in scc and x != head])
            rmap = ODict()
            varmaps = {}

            # import pdb;pdb.set_trace()
            for block in target:
                rmap[block] = newb = BlockProxy(getNewBlockName(block, '+'))

                opmap = ODict([(None,None)])
                varmap = {var:copy.copy(var) for var in block.UCs.keys()}
                newb.UCs = ODict((varmap[k],v) for k,v in block.UCs.items())
                varmaps[newb] = varmap #store this for later use

                for phi in block.phis:
                    new = opmap[phi] = copy.copy(phi)
                    newb.phis.append(new)                
                for line in block.lines:
                    new = opmap[line] = copy.copy(line)
                    newb.lines.append(new)
                newb.jump = block.jump.clone()
                newb.catchset = None if block.catchset is None else block.catchset.copy()

                for var in newb.UCs:
                    var.origin = opmap[var.origin]
                for op in newb.phis + newb.lines:
                    op.replaceVars(varmap)  
                    op.replaceOutVars(varmap)
                newb.jump.replaceVars(varmap)     

                for child,t in newb.getSuccessorPairs():
                    for phi in child.phis:
                        temp = phi.odict.copy()
                        temp[newb,t] = varmap[temp[block,t]]
                        phi.updateDict(temp)

            #Now to replace everything
            affected = rmap.values()
            for newb in rmap.values():
                for phi in newb.phis[:1]:
                    for source,t in phi.odict.keys():
                        if source not in affected and source not in scc:
                            affected.append(source)
            for source in affected:
                for block,t in source.getSuccessorPairs():
                    if block in rmap:
                        newb = rmap[block]
                        # varmap = varmaps[newb]
                        for old,new in zip(block.phis, newb.phis):
                            temp1, temp2 = old.odict.copy(), new.odict.copy()
                            temp2[source,t] = temp1[source,t]
                            # temp2[source,t] = varmap[temp1[source,t]]
                            del temp1[source,t]
                            old.updateDict(temp1)
                            new.updateDict(temp2)
                        source.replaceBlock(block, t, newb)                    

            copies = set(rmap.values())
            # print scc, copies
            for block in scc:
                # print block, block.getSuccessors()
                assert(copies.isdisjoint(block.getSuccessors()))
            

            copies = set(rmap.values())
            blocks.extend(rmap.values())
            newblocks.extend(rmap.values())
            #now recalculate sources and see if our duplication created new sccs we must process
            sources, nsources, esources = getSources(blocks, root)
            newsccs = tarjanSCC(copies, lambda block:([x for x in sources[block] if x in copies]))
            sccs.extend(newsccs)
            assert(not copies.isdisjoint(sources[head]))
            assert(copies.isdisjoint(scc))

        eouter = [(x, True) for x in esources[head] if x not in scc]
        einner = [(x, True) for x in esources[head] if x in scc]

        if eouter:
            new = indirectBlock(head, eouter)
            newblocks.append(new)
            #Be careful because after this pointer, head may temporarily have dual edge types
        if einner:
            new = indirectBlock(head, einner)
            scc = scc + (new,)
            newblocks.append(new)        

        #Now we have everything sorted out, time to recurse
        newblocks += fixSCCHeads(scc, head)
    return newblocks

# def inlineReturns(blocks, nsources):
#     retblocks = [block for block in blocks if isinstance(block.jump, ssa_jumps.Return)]
#     if retblocks:
#         assert(len(retblocks) == 1)
#         current = retblocks[0]
#         retvals = current.jump.params

#         for source in nsources[current]:
#             if source.lines and isinstance(source.lines[-1], ssa_ops.TryReturn):
#                 params = [(val if val.origin is None else val.origin.odict[source,False]) for val in retvals]
#                 del source.lines[-1] #TODO - figure out way to warn when MonitorExitExceptions cannot be ruled out
#                 source.jump = ssa_jumps.Return(None, params)
#                 source.catchset = None

##############################################################################################################
class HandlerInfo(object):
    def __init__(self, handler):
        self.parents = []
        self.children = []
        self.handler = handler
        self.blocks = set()
        # self.catch_tt = catch_tt 
        # self.T #eset for top type

    def extend(self, block, forCatch=False):
        if not self.parents:
            return True

        parent = self.parents[0]
        if block in self.blocks:
            assert(parent.extend(block))
            return True
        if not forCatch and block == self.handler:
            return False
        if not parent.extend(block):
            return False
        for sibling in parent.children:
            if block in sibling.blocks:
                return False
        if not forCatch and block.catchset is not None:
            cs = block.catchset    
            for h, eset in cs.sets.items():
                if self.T & eset:
                    return False
        self.blocks.add(block)
        return True

def fixTryBlocks(blocks, root):
    sources, nsources, esources = getSources(blocks, root)
    dominators = getDominators(root)
    def closure(kernel):
        dom = commonDominator(dominators, kernel)
        return topologicalSort(kernel, lambda block:([] if block == dom else sources[block]))

    EMPTY = exceptionset.ExceptionSet.EMPTY
    minimum = ODict()
    kernel = collections.defaultdict(list)

    for block in blocks:
        if block.catchset is not None:
            for h,eset in block.catchset.sets.items():
                assert(eset)
                minimum[h] = minimum.get(h, EMPTY) | eset 
                kernel[h].append(block)
    handlers = minimum.keys()
    if handlers:
        #set of handlers each handler is less than (higher in try block nesting)
        less = collections.defaultdict(set)
        for h1 in handlers:
            T = minimum[h1].getSingleTType()
            T = exceptionset.ExceptionSet.fromTops(minimum[h1].env, T[0])
            for block in kernel[h1]:
                for h2, eset in block.catchset.sets.items():
                    if h1!=h2 and (T & eset):
                        less[h1].add(h2)

        areas = {h:closure(v) for h,v in kernel.items()}
        for h1,area in areas.items():
            for h2 in handlers:
                if h2 in area:
                    less[h1].add(h2)

        notdone = any(less)
        while notdone:
            notdone = False
            for h1, old in less.items():
                for h2 in old:
                    less[h1] = less[h1] | less[h2]
                if less[h1] != old:
                    notdone = True

        #now make sure partial order is consistent
        for h in handlers:
            if h in less[h]:
                error('Unable to order exceptions')
            less[h] = sorted(less[h], key=handlers.index)
        linear = topologicalSort(handlers, less.get)
        assert(sorted(linear) == sorted(handlers))

        infos = []
        iroot = HandlerInfo(None)
        for h in reversed(linear):
            info = HandlerInfo(h)
            info.catch_tt = minimum[h].getSingleTType()
            info.T = exceptionset.ExceptionSet.fromTops(minimum[h1].env, info.catch_tt[0])
            info.blocks.update(areas[h])
            infos.append(info)

            parent = iroot
            parent.blocks.update(info.blocks)
            nextl = [child for child in parent.children if h in less[child.handler]]
            while nextl:
                if len(nextl) > 1:
                    error('Exception handlers do not form forest')
                parent = nextl[0]
                parent.blocks.update(info.blocks)
                nextl = [child for child in parent.children if h in less[child.handler]]

            parent.children.append(info)
            info.parents.append(parent)

        for info in infos + [iroot]:
            info.blocks = set(closure(info.blocks))
        # printHI(iroot, '')
        # import pdb;pdb.set_trace()
        return list(reversed(infos))
    else:
        return []

def printHI(inf, ind):
    line = ind + '{} -> {}'.format(inf.handler, tuple(inf.blocks))
    print line[:80]
    for child in inf.children:
        printHI(child, ind+'  ')

def structureCFG(blocks, root):
    blocks += makeGraphSimple(blocks, root)

    #Make sure every SCC has a single entry point with purely normal inedges
    blocks += fixSCCHeads(blocks, root)
    assert(len(set(blocks)) == len(blocks))

    sources, nsources, esources = getSources(blocks, root)
    # inlineReturns(blocks, nsources)
    blocks = topologicalSort([root], BlockProxy.getSuccessors) #return block may now be unreachable. If so, remove it

    handlerInfos = fixTryBlocks(blocks, root)
    return blocks, root, handlerInfos
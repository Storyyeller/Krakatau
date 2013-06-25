import itertools, collections, copy
ODict = collections.OrderedDict

from .ssa_types import *
from . import blockmaker,constraints, variablegraph, objtypes, subproc
from . import ssa_jumps, ssa_ops
from ..verifier.descriptors import parseUnboundMethodDescriptor
from .. import graph_util

from .. import opnames
from ..verifier import verifier_types


class SSA_Graph(object):
    entryKey, returnKey, rethrowKey = -1,-2,-3

    def __init__(self, code):
        self._interns = {} #used during initial graph creation to intern variable types
        self.code = code
        self.class_ = code.class_
        self.env = self.class_.env

        method = code.method
        inputTypes, returnTypes = parseUnboundMethodDescriptor(method.descriptor, self.class_.name, method.static)

        #entry point
        funcArgs = [self.makeVarFromVtype(vt, {}) for vt in inputTypes]
        funcInMonad = self.makeVariable(SSA_MONAD)
        entryslots = slots_t(monad=funcInMonad, locals=funcArgs, stack=[])
        self.inputArgs = [funcInMonad] + funcArgs

        entryb = BasicBlock(self.entryKey, lines=[], jump=ssa_jumps.Goto(self, 0))
        entryb.successorStates = ODict([((0, False), entryslots)])
        entryb.tempvars = [x for x in self.inputArgs if x is not None]
        del entryb.sourceStates

        #return 
        newmonad = self.makeVariable(SSA_MONAD)
        newstack = [self.makeVarFromVtype(vt, {}) for vt in returnTypes[:1]] #make sure not to include dummy if returning double/long
        returnb = BasicBlock(self.returnKey, lines=[], jump=ssa_jumps.Return(self, [newmonad] + newstack))
        returnb.inslots = slots_t(monad=newmonad, locals=[], stack=newstack)
        returnb.tempvars = []

        #rethrow
        newmonad, newstack = self.makeVariable(SSA_MONAD), [self.makeVariable(SSA_OBJECT)]
        rethrowb = BasicBlock(self.rethrowKey, lines=[], jump=ssa_jumps.Rethrow(self, [newmonad] + newstack))
        rethrowb.inslots = slots_t(monad=newmonad, locals=[], stack=newstack)
        rethrowb.tempvars = []

        self.entryBlock, self.returnBlock, self.rethrowBlock = entryb, returnb, rethrowb
        self.blocks = None
        # self.procs = '' #used to store information on subprocedues (from the JSR instructions)

    def condenseBlocks(self):
        old = self.blocks
        #Can't do a consistency check on entry as the graph may be in an inconsistent state at this point
        #Since the purpose of this function is to prune unreachable blocks from self.blocks

        sccs = graph_util.tarjanSCC([self.entryBlock], lambda block:block.jump.getSuccessors())
        sccs = list(reversed(sccs))
        self.blocks = list(itertools.chain.from_iterable(map(reversed, sccs)))
        
        assert(set(self.blocks) <= set(old))
        if len(self.blocks) < len(old):
            kept = set(self.blocks)

            for block in self.blocks:
                for phi in block.phis:
                    pairs = [(k,v) for k,v in phi.odict.items() if k[0] in kept]
                    phi.updateDict(pairs)

            if self.returnBlock not in kept:
                self.returnBlock = None
            if self.rethrowBlock not in kept:
                self.rethrowBlock = None        

            for proc in self.procs:
                proc.callops = ODict((op,block) for op,block in proc.callops.items() if block not in kept)
                if proc.callops:
                    assert(proc.target in kept)
                if proc.retblock not in kept:
                    for block in proc.callops.values():
                        block.jump = ssa_jumps.Goto(self, proc.target)
                    proc.callops = None
            self.procs = [proc for proc in self.procs if proc.callops]

    def removeUnusedVariables(self):
        for proc in self.procs:
            keys = proc.callops.keys()[0].out.keys()
            for key in keys:
                if all(op.out[key] is None for op in proc.callops):
                    for op in proc.callops:
                        del op.out[key]
                    del proc.retop.input[key]
        #################################################################
        roots = [x for x in self.inputArgs if x is not None]
        for block in self.blocks:
            roots += block.jump.params
        reachable = graph_util.topologicalSort(roots, lambda var:(var.origin.params if var.origin else []))

        keepset = set(reachable)
        assert(None not in keepset)
        def filterOps(oldops):
            newops = []
            for op in oldops:
                #if any of the params is being removed due to being unreachable, we can assume the whole function can be removed
                keep = keepset.issuperset(op.params) and not keepset.isdisjoint(op.getOutputs())
                if keep:
                    newops.append(op)
                    keepset.update(filter(None, op.getOutputs())) #temp hack
                else:
                    assert(keepset.isdisjoint(op.getOutputs()))
            return newops

        for block in self.blocks:
            block.phis = filterOps(block.phis)
            block.lines = filterOps(block.lines)
            block.filterVarConstraints(keepset)
        #################################################################
        for proc in self.procs:
            for op in proc.callops:
                for k, v in op.out.items():
                    if v not in keepset:
                        op.out[k] = None
            phis = proc.target.phis 
            for op, block in proc.callops.items():
                pvars = set(phi.odict[block,False] for phi in phis)
                op.input = ODict((k,v) for k,v in op.input.items() if v in pvars)
            assert(len(set(tuple(op.input.keys()) for op in proc.callops)) == 1)

    def _getSources(self):
        sources = collections.defaultdict(set)
        for block in self.blocks:
            for child in block.getSuccessors():
                sources[child].add(block)
        return sources

    def mergeSingleSuccessorBlocks(self):
        replace = {}
        removed = set()

        # Make sure that all single jsr procs are inlined first
        self.inlineSubprocs(onlySingle=True)

        sources = self._getSources()
        for block in self.blocks:
            if block in removed:
                continue
            while 1:
                successors = set(block.jump.getSuccessorPairs()) #Warning - make sure not to merge if we have a single successor with a double edge
                if len(successors) != 1:
                    break
                #Even if an exception thrown has single target, don't merge because we need a way to actually access the thrown exception
                if isinstance(block.jump, ssa_jumps.OnException):
                    break

                #We don't bother modifying sources upon merging since the only property we care about is number of successors, which will be unchanged
                child = successors.pop()[0]
                if len(sources[child]) != 1:
                    break

                #We've decided to merge the blocks, now do it
                block.unaryConstraints.update(child.unaryConstraints)

                for phi in child.phis:
                    old, new = phi.rval, phi.params[0]
                    new = replace.get(new,new)
                    replace[old] = new

                    uc1 = block.unaryConstraints[old]
                    uc2 = block.unaryConstraints[new]
                    block.unaryConstraints[new] = constraints.join(uc1, uc2)
                    del block.unaryConstraints[old]
                
                block.lines += child.lines
                block.jump = child.jump

                self.returnBlock = block if child == self.returnBlock else self.returnBlock
                self.rethrowBlock = block if child == self.rethrowBlock else self.rethrowBlock
                for proc in self.procs:
                    proc.retblock = block if child == proc.retblock else proc.retblock
                    #callop values and target obviously cannot be child
                    proc.callops = ODict((op, (block if old==child else old)) for op, old in proc.callops.items())

                #remember to update phis of blocks referring to old child!
                for successor in block.jump.getSuccessors():
                    for phi in successor.phis:
                        phi.replaceBlocks({child:block})

                removed.add(child)
        self.blocks = [b for b in self.blocks if b not in removed]  
        #Fix up replace dict so it can handle multiple chained replacements
        for old in replace.keys()[:]:
            while replace[old] in replace:
                replace[old] = replace[replace[old]]
        if replace:
            for block in self.blocks:
                for op in block.phis + block.lines:
                    op.replaceVars(replace)
                block.jump.replaceVars(replace)

    def disconnectConstantVariables(self):
        for block in self.blocks:
            for var, uc in block.unaryConstraints.items():
                if var.origin is not None:
                    newval = None
                    if var.type[0] == 'int':
                        if uc.min == uc.max:
                            newval = uc.min
                    elif var.type[0] == 'obj':
                        if uc.isConstNull():
                            newval = 'null'

                    if newval is not None:
                        var.origin.removeOutput(var)
                        var.origin = None
                        var.const = newval
            block.phis = [phi for phi in block.phis if phi.rval is not None]
        self._conscheck()

    def _conscheck(self):
        '''Sanity check'''
        sources = self._getSources()
        for block in self.blocks:
            for phi in block.phis:
                if not phi.odict:
                    assert(not sources[block])
                else:
                    parents = zip(*phi.odict)[0]
                    assert(set(parents) == sources[block])

                assert(phi.rval is None or phi.rval in block.unaryConstraints)
                for k,v in phi.odict.items():
                    assert(v.origin is None or v in k[0].unaryConstraints)
                    
        for proc in self.procs:
            for callop in proc.callops:
                assert(set(proc.retop.input) == set(callop.out))

    def constraintPropagation(self):
        #Propagates unary constraints (range, type, etc.) pessimistically and optimistically
        #Assumes there are no subprocedues and this has not been called yet
        assert(not self.procs)

        graph = variablegraph.makeGraph(self.env, self.blocks)
        variablegraph.processGraph(graph)
        for block in self.blocks:
            for var, oldUC in block.unaryConstraints.items():
                newUC = graph[var].output[0]
                # var.name = makename(var)
                if newUC is None:
                    # This variable is overconstrainted, meaning it must be unreachable
                    del block.unaryConstraints[var]

                    if var.origin is not None:
                        var.origin.removeOutput(var)
                        var.origin = None
                    var.name = "UNREACHABLE" #for debug printing
                    # var.name += '-'
                else:
                    newUC = constraints.join(oldUC, newUC)
                    block.unaryConstraints[var] = newUC
        self._conscheck()

    def simplifyJumps(self):
        self._conscheck()

        # Also remove blocks which use a variable detected as unreachable
        def usesInvalidVar(block):
            for op in block.lines:
                for param in op.params:
                    if param not in block.unaryConstraints:
                        return True
            return False

        for block in self.blocks:
            if usesInvalidVar(block):
                for (child,t) in block.jump.getSuccessorPairs():
                    for phi in child.phis:
                        phi.removeKey((block,t))                
                block.jump = None

        #Determine if any jumps are impossible based on known constraints of params: if(0 == 0) etc
        for block in self.blocks:
            if hasattr(block.jump, 'constrainJumps'):
                assert(block.jump.params)
                oldEdges = block.jump.getSuccessorPairs()
                UCs = map(block.unaryConstraints.get, block.jump.params)
                block.jump = block.jump.constrainJumps(*UCs)

                if block.jump is None:
                    #This block has no valid successors, meaning it must be unreachable
                    #It _should_ be removed automatically in the call to condenseBlocks()
                    continue

                newEdges = block.jump.getSuccessorPairs()
                if newEdges != oldEdges:
                    pruned = [x for x in oldEdges if x not in newEdges]
                    for (child,t) in pruned:
                        for phi in child.phis:
                            phi.removeKey((block,t))

        #Unreachable blocks may not automatically be removed by jump.constrainJumps
        #Because it only looks at its own params
        badblocks = set(block for block in self.blocks if block.jump is None)
        newbad = set()
        while badblocks:
            for block in self.blocks:
                if block.jump is None:
                    continue

                badpairs = [(child,t) for child,t in block.jump.getSuccessorPairs() if child in badblocks]
                block.jump = block.jump.reduceSuccessors(badpairs)
                if block.jump is None:
                    newbad.add(block)
            badblocks, newbad = newbad, set()

        self.condenseBlocks()   
        self._conscheck()

    # Subprocedure stuff #####################################################
    def _duplicateRegion(self, region, callblock, target, retblock):
        blockmap = {}
        varmap = {}
        opmap = {None:None}

        newblocks = []
        #create blocks and variables
        for block in region:
            newb = BasicBlock(key=(block.key, callblock.key), lines=None, jump=None)
            del newb.sourceStates
            blockmap[block] = newb
            newblocks.append(newb)

            for var, UC in block.unaryConstraints.items():
                new = copy.copy(var)
                varmap[var] = new
            newb.unaryConstraints = ODict((varmap[var],UC) for var,UC in block.unaryConstraints.items())

        #now fill in phis, ops, and jump
        for block in region:
            newb = blockmap[block]

            newb.phis = []
            for phi in block.phis:
                pairs = [((blockmap.get(sb,sb),t),varmap.get(var,var)) for (sb,t),var in phi.odict.items()]
                new = ssa_ops.Phi(self, ODict(pairs), varmap[phi.rval])
                new.block = newb
                newb.phis.append(new)
                opmap[phi] = new

            newb.lines = []
            for op in block.lines:
                new = copy.copy(op)
                new.replaceVars(varmap)
                new.replaceOutVars(varmap)
                newb.lines.append(new)
                opmap[op] = new

            if block != retblock:
                assert(not isinstance(block.jump, (subproc.ProcCallOp, subproc.DummyRet)))
                new = block.jump.clone()
                new.replaceVars(varmap)
                #jump.replaceBlocks expects to have a valid mapping for every existing block
                #quick hack, create temp dictionary
                tempmap = {b:b for b in new.getSuccessors()}
                tempmap.update(blockmap)
                new.replaceBlocks(tempmap)
                newb.jump = new

            for var in newb.unaryConstraints:
                var.origin = opmap[var.origin]
        
        #now add new blocks into phi dicts of abscond successors
        dupedSet = frozenset(newblocks) | frozenset(region)
        for block in region:
            if block != retblock:
                newb = blockmap[block]
                temp = block.jump.getSuccessorPairs()
                temp = [(k,v) for k,v in temp if k not in dupedSet]

                for child,t in temp:
                    for phi in child.phis:
                        assert((newb,t) not in phi.odict)
                        var = varmap[phi.odict[block,t]]
                        phi.updateDict(phi.odict.items() + [((newb,t), var)])   

        #disconnect from existing jsr target
        for phi in target.phis:
            pairs = [(k,v) for k,v in phi.odict.items() if k[0] != callblock]
            phi.updateDict(pairs)
        return newblocks, blockmap, varmap

    def inlineSubprocs(self, onlySingle=False):
        self._conscheck()
        if not self.procs:
            return
        counter = 0
        #establish DAG of subproc callstacks if we're doing nontrivial inlining, since we can only inline leaf procs
        if not onlySingle:
            sources = self._getSources()
            regions = {}
            for proc in self.procs:
                region = graph_util.topologicalSort([proc.retblock], lambda block:([] if block == proc.target else sources[block]))
                assert(self.entryBlock not in region)
                regions[proc] = frozenset(region)

            parents = {proc:[] for proc in self.procs}
            for x,y in itertools.product(self.procs, repeat=2):
                if regions[x] < regions[y]:
                    parents[x].append(y)
            self.procs = graph_util.topologicalSort(self.procs, parents.get)
            if any(parents.values()):
                print 'Warning, nesting subprocedures detected! This method may take forever to decompile.'

        #now inline the procs
        for proc in reversed(self.procs):
            sources = self._getSources()
            region = graph_util.topologicalSort([proc.retblock], lambda block:([] if block == proc.target else sources[block]))

            pairs = proc.callops.items()
            while (len(pairs) == 1) or (not onlySingle and len(pairs) >= 1):
                callop, callblock = pairs.pop()

                if pairs:
                    assert(not onlySingle)
                    newblocks, blockmap, varmap = self._duplicateRegion(region, callblock, proc.target, proc.retblock)
                    self.blocks += newblocks

                    newregion = newblocks
                    newEntryBlock = blockmap[proc.target]
                    newExitBlock = blockmap[proc.retblock]
                    print 'Inlining subroutine with {} blocks'.format(len(newregion))
                else: #if there's only one call left, don't duplicate, just inline in place
                    newregion = region
                    newEntryBlock = proc.target
                    newExitBlock = proc.retblock
                    varmap = {}

                #now fill in JSR specific stuff and insert it
                #add jump to newexit first so it can safely be accessed in skipvar loop
                newExitBlock.jump = ssa_jumps.Goto(self, callop.fallthrough)

                #first we find any vars that bypass the proc since we have to pass them through the new blocks
                skipvars = [phi.odict[callblock,False] for phi in callop.fallthrough.phis]
                skipvars = [var for var in skipvars if var.origin is not callop]

                svarcopy = {}
                newphis = {}
                for var, block in itertools.product(skipvars, newregion):
                    svarcopy[var, block] = new = copy.copy(var)
                    phi = ssa_ops.Phi(self, [], new)
                    phi.block = block
                    new.origin = phi 
                    block.phis.append(phi)
                    newphis[var, block] = phi 
                    block.unaryConstraints[new] = callblock.unaryConstraints[var]

                for var, block in itertools.product(skipvars, newregion):
                    for child, t in block.jump.getSuccessorPairs():
                        if child in newregion:
                            phi = newphis[var, child]
                            phi.updateDict(phi.odict.items() + [((block,t), svarcopy[var,block])])

                #Fix phis of entryblock
                for phi in newEntryBlock.phis:
                    if phi.odict:
                        pair = (callblock,False), phi.odict[callblock,False]
                        phi.updateDict([pair])
                for var in skipvars:
                    phi = newphis[var, newEntryBlock]
                    pair = (callblock,False), var
                    phi.updateDict([pair])

                ftblock = callop.fallthrough
                callblock.jump = ssa_jumps.Goto(self, newEntryBlock)

                #Now handle exit
                retVarMap = {}
                for key, var in callop.out.items():
                    old = proc.retop.input[key]
                    retVarMap[var] = varmap.get(old,old) #for inplace inlining, varmap is empty
                for var in skipvars:
                    retVarMap[var] = svarcopy[var, newExitBlock]

                for phi in callop.fallthrough.phis:
                    pair = (newExitBlock,False), retVarMap[phi.odict[callblock, False]]
                    phi.updateDict([pair])
                counter += 1

            proc.callops = ODict(pairs)
        self.procs = [proc for proc in self.procs if proc.callops]
        if counter:
            print counter, 'subprocedure calls inlined'
        self._conscheck()
    ##########################################################################

    #assign variable names for debugging
    varnum = collections.defaultdict(itertools.count) 
    def makeVariable(self, *args, **kwargs):
        var = Variable(*args, **kwargs)
        pref = args[0][0][0]
        # var.name = pref + str(next(self.varnum[pref]))
        return var

    def makeVarFromVtype(self, vtype, initMap):
        vtype = initMap.get(vtype, vtype)
        type_ = verifierToSSAType(vtype)
        if type_ is not None:
            var = self.makeVariable(type_)
            if type_ == SSA_OBJECT:
                # Intern the variable object types to save a little memory
                # in the case of excessively long methods with large numbers
                # of identical variables, such as sun/util/resources/TimeZoneNames_*
                tt = objtypes.verifierToSynthetic(vtype)
                var.decltype = self._interned(tt)
            return var
        return None

    def _interned(self, x):
        try:
            return self._interns[x]
        except KeyError:
            if len(self._interns) < 256: #arbitrary limit
                self._interns[x] = x
            return x 

    def getConstPoolArgs(self, index):
        return self.class_.cpool.getArgs(index)

    def getConstPoolType(self, index):
        return self.class_.cpool.getType(index)

    def rawExceptionHandlers(self):
        rethrow_handler = (0, self.code.codelen, self.rethrowKey, 0)
        return self.code.except_raw + [rethrow_handler]

def makePhiFromODict(parent, outvar, d, getter):
    pairs = [(k,getter(v)) for k,v in d.items()]
    return ssa_ops.Phi(parent, ODict(pairs), outvar)

def isTerminal(parent, block):
    return block is parent.returnBlock or block is parent.rethrowBlock

def ssaFromVerified(code, iNodes):
    parent = SSA_Graph(code)

    #create map of uninitialized -> initialized types so we can convert them
    initMap = {}
    for node in iNodes:
        if node.op == opnames.NEW:
            initMap[node.push_type] = node.target_type
    initMap[verifier_types.T_UNINIT_THIS] = verifier_types.T_OBJECT(code.class_.name)

    blocks = [blockmaker.fromInstruction(parent, iNode, initMap) for iNode in iNodes if iNode.visited]
    blocks = [parent.entryBlock] + blocks + [parent.returnBlock, parent.rethrowBlock]
    blockDict = {b.key:b for b in blocks}

    #fixup proc info
    jsrs = [block for block in blocks if isinstance(block.jump, subproc.ProcCallOp)]
    procs = ODict((block.jump.target, subproc.ProcInfo(block)) for block in blocks if isinstance(block.jump, subproc.DummyRet))
    for block in jsrs:
        target = blockDict[block.jump.iNode.successors[0]]
        callop = block.jump
        retblock = blockDict[block.jump.iNode.returnedFrom]
        retop = retblock.jump
        assert(isinstance(callop, subproc.ProcCallOp))
        assert(isinstance(retop, subproc.DummyRet))

        #merge states from inodes to create out
        jsrslots = block.successorStates[target.key, False]

        retslots = retblock.successorStates[callop.iNode.next_instruction, False]
        del retblock.successorStates[callop.iNode.next_instruction, False]

        #Create new variables (will have origin set to callop in registerOuts)
        #Even for skip vars, we temporarily create a variable coming from the ret
        #But it won't be used, and will be later pruned anyway
        newstack = map(copy.copy, retslots.stack)
        newlocals = map(copy.copy, retslots.locals)
        newmonad = copy.copy(retslots.monad)
        newslots = slots_t(monad=newmonad, locals=newlocals, stack=newstack)
        callop.registerOuts(newslots)
        block.tempvars += callop.out.values()

        #The successor state uses the merged locals so it gets skipvars
        zipped = itertools.izip_longest(newlocals, jsrslots.locals, fillvalue=None)
        mask = [mask for entry,mask in retop.iNode.masks if entry==target.key][0]
        merged = [(x if i in mask else y) for i,(x,y) in enumerate(zipped)]
        merged_slots = slots_t(monad=newmonad, locals=merged, stack=newstack)

        block.successorStates[callop.iNode.next_instruction, False] = merged_slots
        
        proc = procs[target.key]
        proc.callops[callop] = block 
        assert(proc.target == target.key and proc.retblock == retblock and proc.retop == retop)
        del callop.iNode 
    #Now delete iNodes and fix extra input variables
    procs = procs.values()
    for proc in procs:
        del proc.retop.iNode
        assert(not proc.retblock.successorStates)
        proc.target = blockDict[proc.target]

        ops = proc.callops
        keys = set.intersection(*(set(op.input.keys()) for op in ops))
        for op in ops:
            op.input = ODict((k,v) for k,v in op.input.items() if k in keys)
    parent.procs = procs

    #Propagate successor info
    for block in blocks:
        if isTerminal(parent, block):
            continue

        assert(set(block.jump.getNormalSuccessors()) == set([k for (k,t),o in block.successorStates.items() if not t]))
        assert(set(block.jump.getExceptSuccessors()) == set([k for (k,t),o in block.successorStates.items() if t]))

        #replace the placeholder keys with actual blocks now
        block.jump.replaceBlocks(blockDict)
        for (key, exc),outstate in block.successorStates.items():
            dest = blockDict[key]
            assert(dest.sourceStates.get((block,exc), outstate) == outstate)
            dest.sourceStates[block,exc] = outstate
        del block.successorStates

    #create phi functions for input variables
    for block in blocks:
        if block is parent.entryBlock:
            block.phis = []
            continue
        ins = block.inslots

        ins.monad.origin = makePhiFromODict(parent, ins.monad, block.sourceStates, (lambda i: i.monad))
        for k, v in enumerate(ins.stack):
            if v is not None:
                v.origin = makePhiFromODict(parent, v, block.sourceStates, (lambda i: i.stack[k]))
        for k, v in enumerate(ins.locals):
            if v is not None:
                v.origin = makePhiFromODict(parent, v, block.sourceStates, (lambda i: i.locals[k]))
                assert(v.origin.rval is v)

        del block.sourceStates, block.inslots
        phivars = [ins.monad] + ins.stack + ins.locals
        block.phis = [var.origin for var in phivars if var is not None]

        for phi in block.phis: #??
            phi.block = block

        for phi in block.phis:
            types = [var.type for var in phi.odict.values()]
            assert(not types or set(types) == set([phi.rval.type]))

    #Important to intern constraints to save memory on aforementioned excessively long methods
    def makeConstraint(var, _cache={}):
        key = var.type, var.const, var.decltype
        try:
            return _cache[key]
        except KeyError:
            _cache[key] = temp = constraints.fromVariable(parent.env, var)
            return temp

    #create unary constraints for each variable
    for block in blocks:
        bvars = list(block.tempvars)
        del block.tempvars
        assert(None not in bvars)
        
        bvars += [phi.rval for phi in block.phis]
        for op in block.lines:
            bvars += op.params
            bvars += [x for x in op.getOutputs() if x is not None]
        bvars += block.jump.params

        for var in bvars:
            block.unaryConstraints[var] = makeConstraint(var)

    #Make sure that branch targets are distinct, since this is assumed everywhere
    #Only necessary for if statements as the other jumps merge targets automatically
    for block in blocks:
        block.jump = block.jump.reduceSuccessors([])
    parent.blocks = blocks
    
    del parent._interns #no new variables should be created from vtypes after this point. Might as well free it
    parent._conscheck()
    return parent
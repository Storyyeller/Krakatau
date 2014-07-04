import itertools, collections, copy

from . import blockmaker, constraints, variablegraph, objtypes, subproc
from . import ssa_jumps, ssa_ops
from ..verifier.descriptors import parseUnboundMethodDescriptor
from .. import graph_util

from .ssa_types import SSA_OBJECT, BasicBlock, verifierToSSAType

class SSA_Variable(object):
    __slots__ = 'type','origin','name','const','decltype','uninit_orig_num'

    def __init__(self, type_, origin=None, name=""):
        self.type = type_       # SSA_INT, SSA_OBJECT, etc.
        self.origin = origin
        self.name = name
        self.const = None
        self.decltype = None #for objects, the inferred type from the verifier if any
        self.uninit_orig_num = None #if uninitialized, the bytecode offset of the new instr

    #for debugging
    def __str__(self):
        return self.name if self.name else super(SSA_Variable, self).__str__()

    def __repr__(self):
        name =  self.name if self.name else "@" + hex(id(self))
        return "Var {}".format(name)

#This class is the main IR for bytecode level methods. It consists of a control
#flow graph (CFG) in static single assignment form (SSA). Each node in the
#graph is a BasicBlock. This consists of a list of phi statements representing
#inputs, a list of operations, and a jump statement. Exceptions are represented
#explicitly in the graph with the OnException jump. Each block also keeps track
#of the unary constraints on the variables in that block.

#Handling of subprocedures is rather annoying. Each complete subproc has an associated
#ProcInfo while jsrs and rets are represented by ProcCallOp and DummyRet respectively.
#The jsrblock has the target and fallthrough as successors, while the fallthrough has
#the jsrblock as predecessor, but not the retblock. Control flow paths where the proc
#never returns are represented by ordinary jumps from blocks in the procedure to outside
#Successful completion of the proc is represented by the fallthrough edge. The fallthrough
#block gets its variables from the jsrblock, including skip vars which don't depend on the
#proc, and variables from jsr.output which represent what would have been returned from ret
#Every proc has a reachable retblock. Jsrs with no associated ret are simply turned
#into gotos during the initial basic block creation.

class SSA_Graph(object):
    entryKey = blockmaker.ENTRY_KEY

    def __init__(self, code):
        self.code = code
        self.class_ = code.class_
        self.env = self.class_.env

        self.inputArgs = None
        self.entryBlock = None
        self.blocks = None
        self.procs = None #used to store information on subprocedues (from the JSR instructions)

        self.block_numberer = itertools.count(-4,-1)

    def condenseBlocks(self):
        assert(not self.procs)
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
                for pair in block.predecessors[:]:
                    if pair[0] not in kept:
                        block.removePredPair(pair)

    def removeUnusedVariables(self):
        assert(not self.procs)
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
                    for v in op.getOutputs():
                        if v and v not in keepset:
                            op.removeOutput(v)
                else:
                    assert(keepset.isdisjoint(op.getOutputs()))
            return newops

        for block in self.blocks:
            block.phis = filterOps(block.phis)
            block.lines = filterOps(block.lines)
            block.filterVarConstraints(keepset)

    def _getSources(self): #TODO - remove
        sources = collections.defaultdict(set)
        for block in self.blocks:
            for child in block.getSuccessors():
                sources[child].add(block)
        for block in self.blocks:
            assert(sources[block] == set(x for x,t in block.predecessors))
        return sources

    def mergeSingleSuccessorBlocks(self):
        assert(not self.procs) # Make sure that all single jsr procs are inlined first

        replace = {}
        removed = set()
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
                child, jtype = successors.pop()
                if len(sources[child]) != 1:
                    break

                #We've decided to merge the blocks, now do it
                block.unaryConstraints.update(child.unaryConstraints)
                for phi in child.phis:
                    assert(len(phi.dict) == 1)
                    old, new = phi.rval, phi.get((block, jtype))
                    new = replace.get(new,new)
                    replace[old] = new

                    uc1 = block.unaryConstraints[old]
                    uc2 = block.unaryConstraints[new]
                    block.unaryConstraints[new] = constraints.join(uc1, uc2)
                    del block.unaryConstraints[old]

                block.lines += child.lines
                block.jump = child.jump
                #remember to update phis of blocks referring to old child!
                for successor,t in block.jump.getSuccessorPairs():
                    successor.replacePredPair((child,t), (block,t))
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
            assert(sources[block] == {k for k,t in block.predecessors})
            for phi in block.phis:
                assert(phi.rval is None or phi.rval in block.unaryConstraints)
                for k,v in phi.dict.items():
                    assert(v.name == "UNREACHABLE" or v in k[0].unaryConstraints)
        keys = [block.key for block in self.blocks]
        assert(len(set(keys)) == len(keys))
        temp = [self.entryBlock]
        for proc in self.procs:
            temp += [proc.target, proc.retblock]
            temp += proc.jsrblocks
        assert(len(set(temp)) == len(temp))

    def constraintPropagation(self):
        #Propagates unary constraints (range, type, etc.) pessimistically and optimistically
        #Assumes there are no subprocedues and this has not been called yet
        assert(not self.procs)
        varnodes, result_lookup = variablegraph.makeGraph(self.env, self.blocks)
        variablegraph.processGraph(varnodes)
        for block in self.blocks:
            for var, oldUC in block.unaryConstraints.items():
                newUC = result_lookup[var].output[0]
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
                    child.removePredPair((block,t))
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
                        child.removePredPair((block,t))

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
    def _copyBlock(self, block):
        b = BasicBlock(next(self.block_numberer))
        self.blocks.append(b)
        return b

    def _copyVar(self, var, vard=None):
        v = copy.copy(var)
        v.name = v.origin = None #TODO - generate new names?
        if vard is not None:
            vard[var] = v
        return v

    def _region(self, proc):
        region = graph_util.topologicalSort([proc.retblock], lambda block:[] if block == proc.target else [b for b,t in block.predecessors])
        temp = set(region)
        assert(self.entryBlock not in temp and proc.target in temp and temp.isdisjoint(proc.jsrblocks))
        return region

    def _splitSubProc(self, proc):
        #Splits a proc into two, with one callsite using the new proc instead
        #this involves duplicating the body of the procedure
        #the new proc is appended to the list of procs so it can work properly
        #with the stack processing in inlineSubprocs
        assert(len(proc.jsrblocks) > 1)
        target, retblock = proc.target, proc.retblock
        region = self._region(proc)
        blockd_all = {b:b for b in self.blocks}

        blockd, vard = {}, {}
        for oldb in region:
            block = blockd[oldb] = self._copyBlock(oldb)
            block.unaryConstraints = {self._copyVar(k, vard):v for k,v in oldb.unaryConstraints.items()}
            block.phis = [ssa_ops.Phi(block, vard[oldphi.rval]) for oldphi in oldb.phis]

            for op in oldb.lines:
                new = copy.copy(op)
                new.replaceVars(vard)
                new.replaceOutVars(vard)
                assert(new.getOutputs().count(None) == op.getOutputs().count(None))
                for outv in new.getOutputs():
                    if outv is not None:
                        assert(outv.origin is None)
                        outv.origin = new
                block.lines.append(new)

            block.jump = oldb.jump.clone()
            block.jump.replaceVars(vard)

        #can't fix up jump blocks until they've all been created, obviously
        blockd_all.update(blockd)
        for oldb, block in blockd.items():
            block.jump.replaceBlocks(blockd_all)
            for suc, t in block.jump.getSuccessorPairs():
                suc.predecessors.append((block, t))

        for old, new in vard.items():
            assert(type(old.origin) == type(new.origin))

        for oldb, block in blockd.items():
            for oldc, t in oldb.jump.getSuccessorPairs():
                child = blockd_all[oldc]
                assert(len(child.phis) == len(oldc.phis))
                for phi1, phi2 in zip(oldc.phis, child.phis):
                    phi2.add((block, t), vard[phi1.get((oldb, t))])

        #now fix up entry points to subproc
        split_jsrs = [proc.jsrblocks.pop()]
        target2 = blockd[target]
        assert(len(target.phis) == len(target2.phis))
        for jsr in split_jsrs:
            key = jsr, False
            for phi1, phi2 in zip(target.phis, target2.phis):
                phi2.add(key, phi1.get(key))
                del phi1.dict[key]
            #fix up jsr predecessors/successors
            target.predecessors.remove(key)
            target2.predecessors.append(key)
            assert(jsr.jump.target == target)
            jsr.jump.target = target2

        newproc = subproc.ProcInfo(blockd[proc.retblock], blockd[proc.target])
        newproc.jsrblocks = split_jsrs
        return newproc

    def _inlineSubProc(self, proc):
        #Inline a proc with single callsite in place
        assert(len(proc.jsrblocks) == 1)
        target, retblock = proc.target, proc.retblock
        region = self._region(proc)

        jsrblock = proc.jsrblocks[0]
        jsrop = jsrblock.jump
        ftblock = jsrop.fallthrough

        #first we find any vars that bypass the proc since we have to pass them through the new blocks
        skipvars = [phi.get((jsrblock,False)) for phi in ftblock.phis]
        skipvars = [var for var in skipvars if var.origin is not jsrop]
        #will need to change if we ever add a pass to create new skipvars
        assert(set(skipvars) <= jsrop.debug_skipvars)

        svarcopy = {(var, block):self._copyVar(var) for var, block in itertools.product(skipvars, region)}
        for var, block in itertools.product(skipvars, region):
            rval = svarcopy[var, block]
            phi = ssa_ops.Phi(block, rval)
            block.phis.append(phi)
            block.unaryConstraints[rval] = jsrblock.unaryConstraints[var]

            if block == target:
                assert(block.predecessors == [(jsrblock, False)])
                phi.add(block.predecessors[0], var)
            else:
                for key in block.predecessors:
                    phi.add(key, svarcopy[var, key[0]])

        outreplace = {jv:rv for jv, rv in zip(jsrblock.jump.output, retblock.jump.input) if jv is not None}
        for var in outreplace: #don't need jsrop's out vars anymore
            del jsrblock.unaryConstraints[var]

        for var in skipvars:
            outreplace[var] = svarcopy[var, retblock]
        jsrblock.jump = ssa_jumps.Goto(self, target)
        retblock.jump = ssa_jumps.Goto(self, ftblock)

        ftblock.replacePredPair((jsrblock, False), (retblock, False))
        for phi in ftblock.phis:
            phi.replaceVars(outreplace)

    def inlineSubprocs(self):
        self._conscheck()
        if not self.procs:
            return

        #establish DAG of subproc callstacks if we're doing nontrivial inlining, since we can only inline leaf procs
        regions = {proc:frozenset(self._region(proc)) for proc in self.procs}
        parents = {proc:[] for proc in self.procs}
        for x,y in itertools.product(self.procs, repeat=2):
            if not regions[y].isdisjoint(x.jsrblocks):
                parents[x].append(y)

        self.procs = graph_util.topologicalSort(self.procs, parents.get)
        if any(parents.values()):
            print 'Warning, nesting subprocedures detected! This method may take a long time to decompile.'

        #now inline the procs
        while self.procs:
            proc = self.procs.pop()
            while len(proc.jsrblocks) > 1:
                print 'splitting', proc
                #push new subproc onto stack
                self.procs.append(self._splitSubProc(proc))
                self._conscheck()
            print 'inlining', proc
            self._inlineSubProc(proc)
            self._conscheck()
    ##########################################################################
    #assign variable names for debugging
    varnum = collections.defaultdict(itertools.count)
    def makeVariable(self, *args, **kwargs):
        var = SSA_Variable(*args, **kwargs)
        # pref = args[0][0][0].replace('o','a')
        # var.name = pref + str(next(self.varnum[pref]))
        return var

    def setObjVarData(self, var, vtype, initMap):
        vtype2 = initMap.get(vtype, vtype)

        # Intern the variable object types to save a little memory
        # in the case of excessively long methods with large numbers
        # of identical variables, such as sun/util/resources/TimeZoneNames_*
        # TODO: probably not necessary any more due to other optimizations
        tt = objtypes.verifierToSynthetic(vtype2)
        assert(var.decltype is None or var.decltype == tt)
        var.decltype = tt
        #if uninitialized, record the offset of originating new instruction for later
        if vtype.tag == '.new':
            assert(var.uninit_orig_num is None or var.uninit_orig_num == vtype.extra)
            var.uninit_orig_num = vtype.extra

    def makeVarFromVtype(self, vtype, initMap):
        vtype2 = initMap.get(vtype, vtype)
        type_ = verifierToSSAType(vtype2)
        if type_ is not None:
            var = self.makeVariable(type_)
            if type_ == SSA_OBJECT:
                self.setObjVarData(var, vtype, initMap)
            return var
        return None

    def getConstPoolArgs(self, index):
        return self.class_.cpool.getArgs(index)

    def getConstPoolType(self, index):
        return self.class_.cpool.getType(index)

def ssaFromVerified(code, iNodes):
    method = code.method
    inputTypes, returnTypes = parseUnboundMethodDescriptor(method.descriptor, method.class_.name, method.static)

    parent = SSA_Graph(code)
    data = blockmaker.BlockMaker(parent, iNodes, inputTypes, returnTypes, code.except_raw)

    parent.blocks = blocks = data.blocks
    parent.entryBlock = data.entryBlock
    parent.inputArgs = data.inputArgs
    assert(parent.entryBlock in blocks)

    #create subproc info
    procd = {block.jump.target:subproc.ProcInfo(block, block.jump.target) for block in blocks if isinstance(block.jump, subproc.DummyRet)}
    for block in blocks:
        if isinstance(block.jump, subproc.ProcCallOp):
            procd[block.jump.target].jsrblocks.append(block)
    parent.procs = sorted(procd.values(), key=lambda p:p.target.key)

    # Intern constraints to save a bit of memory for long methods
    def makeConstraint(var, _cache={}):
        key = var.type, var.const, var.decltype
        try:
            return _cache[key]
        except KeyError:
            _cache[key] = temp = constraints.fromVariable(parent.env, var)
            return temp

    #create unary constraints for each variable
    for block in blocks:
        bvars = []
        if isinstance(block.jump, subproc.ProcCallOp):
            bvars += block.jump.output
        #entry block has no phis
        if block is parent.entryBlock:
            bvars += parent.inputArgs

        bvars = [v for v in bvars if v is not None]
        bvars += [phi.rval for phi in block.phis]
        for op in block.lines:
            bvars += op.params
            bvars += [x for x in op.getOutputs() if x is not None]
        bvars += block.jump.params

        for suc, t in block.jump.getSuccessorPairs():
            for phi in suc.phis:
                bvars.append(phi.get((block, t)))
        assert(None not in bvars)
        block.unaryConstraints = {var:makeConstraint(var) for var in set(bvars)}
    parent._conscheck()
    return parent
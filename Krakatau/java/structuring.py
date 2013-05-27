import collections, itertools
ddict = collections.defaultdict

from .. import graph_util
from . import graphproxy

from ..ssa import ssa_jumps
from ..ssa.exceptionset import ExceptionSet
from .setree import SEBlockItem, SEScope, SEIf, SESwitch, SETry, SEWhile

# This module is responsible for transforming an arbitrary control flow graph into a tree
# of nested structures corresponding to Java control flow statements. This occurs in 
# several main steps
#
# Preprocessing - create graph view and ensure that there are no self loops and every node
#   has only one incoming edge type
# Structure loops - ensure every loop has a single entry point. This may result in 
#   exponential code duplication in pathological cases
# Structure exceptions - create dummy nodes for every throw exception type for every node
# Structure conditionals - order switch targets consistent with fallthrough and create
#   dummy nodes where necessary
# Create constraints - sets up the constraints used to represent nested statements
# Merge exceptions - try to merge as any try constraints as possible. This is done by
#   extending one until it covers the cases that another one handles, allowing the second
#   to be removed
# Parallelize exceptions - freeze try constraints and turn them into multicatch blocks
#   where possible (not implemented yet)
# Complete scopes - expand scopes to try to reduce the number of successors
# Add break scopes - add extra scope statements so extra successors can be represented as
#   labeled breaks

#########################################################################################
class DominatorInfo(object):
    def __init__(self, root):
        self._doms = doms = {root:(root,)}
        stack = [root]
        while stack:
            cur = stack.pop()
            for child in cur.successors:
                new = doms[cur] + (child,)
                old = doms.get(child)
                if new != old:
                    new = new if old is None else tuple(x for x in old if x in new)
                    assert(child in new)
                if new != old:
                    doms[child] = new
                    if child not in stack:
                        stack.append(child)
        self.nodeset = set(self._doms)
        self.root = root

    def dominators(self, node):
        return self._doms[node]

    def dominator(self, nodes):
        '''Get the common dominator of nodes'''
        return [x for x in zip(*map(self._doms.get, nodes)) if len(set(x))==1][-1][0]

    def area(self, node):
        #Note, if changed to store a set, make sure to copy it, as returned sets are mutated
        return set(k for k,v in self._doms.items() if node in v)

    def extend(self, nodes):
        dom = self.dominator(nodes)
        temp = graph_util.topologicalSort(nodes, lambda x:([] if x is dom else x.predecessors))
        return set(temp)

#########################################################################################
class ScopeConstraint(object):
    def __init__(self, lbound, ubound):
        self.lbound = lbound
        self.ubound = ubound

_count = itertools.count()
_gcon_tags = 'while','try','switch','if','scope'
class CompoundConstraint(object):
    def __init__(self, tag, head, scopes):
        assert(tag in _gcon_tags)
        self.tag = tag
        self.scopes = scopes
        self.head = head
        self.heads = frozenset([head]) if head is not None else frozenset()
        #only used by try constraints, but we leave dummy sets for the rest
        self.forcedup = self.forceddown = frozenset()

        self.lbound = set().union(*[scope.lbound for scope in self.scopes])
        self.ubound = set().union(*[scope.ubound for scope in self.scopes])
        if head is not None:
            self.lbound.add(head)
            self.ubound.add(head)
        assert(self.ubound >= self.lbound)
        self.id = next(_count) #for debugging purposes

    def __str__(self): return self.tag+str(self.id)
    __repr__ = __str__

def WhileCon(dom, head):
    ubound = dom.area(head)
    lbound = set(dom.extend([head] + [n2 for n2 in head.predecessors if n2 in ubound]))
    assert(len(lbound)>1)
    return CompoundConstraint('while', None, [ScopeConstraint(lbound, ubound)])

def TryCon(trynode, target, cset, catchvar):
    trybound = set([trynode])
    tryscope = ScopeConstraint(trybound, trybound.copy())

    new = CompoundConstraint('try', None, [tryscope])
    new.forcedup = set()
    new.forceddown = set()
    new.target = target
    new.cset = cset
    new.catchvar = catchvar

    assert(len(new.target.successors) == 1)
    new.orig_target = new.target.successors[0]
    return new

def FixedScopeCon(lbound):
    return CompoundConstraint('scope', None, [ScopeConstraint(lbound, lbound.copy())])
#########################################################################################

def structureLoops(nodes):
    todo = nodes
    while_heads = []
    while todo:
        newtodo = []
        temp = set(todo)
        sccs = graph_util.tarjanSCC(todo, lambda block:[x for x in block.predecessors if x in temp])

        for scc in sccs:
            if len(scc) <= 1:
                continue

            scc_set = set(scc)
            entries = [n for n in scc if not scc_set.issuperset(n.predecessors)]
            #if more than one entry point into the loop, we have to choose one as the head and duplicate the rest
            #just choose arbitrarily for now
            head = entries.pop()

            if entries:
                reachable = graph_util.topologicalSort(entries, 
                    lambda block:[x for x in block.successors if x in scc_set and x is not head])

                newnodes = graphproxy.duplicateNodes(reachable, scc_set)
                newtodo += newnodes
                nodes += newnodes
                print 'Warning, multiple entry point loop detected. Generated code may be extremely large'

            newtodo.extend(scc)
            newtodo.remove(head)
            while_heads.append(head)
        todo = newtodo   
    return while_heads 

def structureExceptions(nodes):
    thrownodes = [n for n in nodes if n.block and isinstance(n.block.jump, ssa_jumps.OnException)]

    newinfos = []
    for n in thrownodes:
        manager = n.block.jump.cs
        thrownvar = n.block.jump.params[0]

        mycsets = {}
        mytryinfos = []
        newinfos.append((n, manager.mask, mycsets, mytryinfos))

        temp = ExceptionSet.EMPTY
        for cset in manager.sets.values():
            assert(not temp & cset)
            temp |= cset
        assert(temp == manager.mask)

        for handler, cset in manager.sets.items():
            en = n.blockdict[handler.key, True]
            mycsets[en] = cset

            en.predecessors.remove(n)
            n.successors.remove(en)

            caughtvars = [v2 for (v1,v2) in zip(n.outvars[en], en.invars) if v1 == thrownvar]
            assert(len(caughtvars) <= 1)
            caughtvar = caughtvars.pop() if caughtvars else None

            outvars = [(None if v == thrownvar else v) for v in n.outvars[en]]
            del n.outvars[en]

            for tt in cset.getTopTTs():
                top = ExceptionSet.fromTops(cset.env, tt[0])
                new = en.indirectEdges([])
                new.predecessors.append(n)
                n.successors.append(new)
                n.eassigns[new] = outvars #should be safe to avoid copy as we'll never modify it
                nodes.append(new)
                mytryinfos.append((top, new, caughtvar))

    return newinfos

def structureConditionals(entryNode, nodes):
    dom = DominatorInfo(entryNode)
    switchnodes = [n for n in nodes if n.block and isinstance(n.block.jump, ssa_jumps.Switch)]    
    ifnodes = [n for n in nodes if n.block and isinstance(n.block.jump, ssa_jumps.If)]    

    #For switch statements, we can't just blithley indirect all targets as that interferes with fallthrough behavior
    switchinfos = []
    for n in switchnodes:
        # import pdb;pdb.set_trace()
        targets = n.successors
        bad = [x for x in targets if n not in dom.dominators(x)]
        good = [x for x in targets if x not in bad]

        domains = {x:dom.area(x) for x in good}
        parents = {}
        for x in good:
            parents[x] = [k for k,v in domains.items() if not v.isdisjoint(x.predecessors)]
            if x in parents[x]:
                parents[x].remove(x)
        
        #We need to make sure that the fallthrough graph consists of independent chains
        #For targets with multiple parents, both parents must be removed
        #For a target with multiple children, all but one of the children must be removed
        depthfirst = graph_util.topologicalSort(good, parents.get)
        chosenChild = {}
        for target in depthfirst:
            if parents[target]:
                isOk = len(parents[target]) == 1 and parents[target][0] in parents
                isOk = isOk and chosenChild.setdefault(parents[target][0], target) == target
                if not isOk:
                    bad.append(target)
                    good.remove(target)
                    del domains[target], parents[target]

        #Now we need an ordering of the good blocks consistent with fallthrough
        #regular topoSort can't be used since we require chains to be immediately contiguous
        #which a topological sort doesn't garuentee
        leaves = [x for x in good if x not in chosenChild]
        ordered = []
        for leaf in leaves:
            cur = leaf
            ordered.append(cur)
            while parents[cur]:
                assert(chosenChild[parents[cur][0]] == cur)
                cur = parents[cur][0]
                ordered.append(cur)
        ordered = ordered[::-1]

        for x in bad:
            new = x.indirectEdges([n])
            nodes.append(new)
            ordered.append(new)
        assert(len(ordered) == len(targets) == (len(good) + len(bad)))
        switchinfos.append((n, ordered))

    ifinfos = []
    for n in ifnodes:
        targets = n.successors[:]
        targets = [x.indirectEdges([n]) for x in targets]
        nodes.extend(targets)
        ifinfos.append((n, targets))

    return switchinfos, ifinfos

def createConstraints(dom, while_heads, newtryinfos, switchinfos, ifinfos):
    constraints = []
    for head in while_heads:
        constraints.append(WhileCon(dom, head))

    forbid_dicts = ddict(dict)
    for n, mask, csets, tryinfos in newtryinfos:
        if len(csets)>1:
            for ot, cset in csets.items():
                forbid_dicts[ot][n] = mask - cset    

    for n, mask, csets, tryinfos in newtryinfos:
        cons = [TryCon(n, target, top, caughtvar) for top, target, caughtvar in tryinfos]

        for con, con2 in itertools.product(cons, repeat=2):
            if con is con2:
                continue
            if not (con.cset - con2.cset): #cset1 is subset of cset2
                assert(con2.cset - con.cset)
                con.forcedup.add(con2)
                con2.forceddown.add(con)

        for con in cons:
            con.forbidden = forbid_dicts[con.orig_target].copy()

            if n in con.forbidden:
                for con2 in con.forceddown:
                    con.forbidden[n] -= con2.cset
                assert(con.cset.isdisjoint(con.forbidden[n]))
                if not con.forbidden[n]:
                    del con.forbidden[n]

            assert(all(con.forbidden.values()))
        constraints.extend(cons)

    for n, ordered in switchinfos:
        last = []
        scopes = []
        for target in reversed(ordered):
            fallthroughs = [x for x in last if target in dom.dominators(x)]
            assert(n not in fallthroughs)
            last = target.predecessors

            lbound = dom.extend([target] + fallthroughs)
            ubound = dom.area(target)
            assert(lbound <= ubound and n not in ubound)
            scopes.append(ScopeConstraint(lbound, ubound))
        con = CompoundConstraint('switch', n, list(reversed(scopes)))
        constraints.append(con)

    for n, targets in ifinfos:
        scopes = []
        for target in targets:
            lbound = set([target])
            ubound = dom.area(target)
            scopes.append(ScopeConstraint(lbound, ubound))
        con = CompoundConstraint('if', n, scopes)
        constraints.append(con)

    return constraints

def orderConstraints(dom, constraints, nodes):
    DummyParent = None #dummy root
    children = ddict(list)
    frozen = set()

    dset = frozenset(dom._doms)

    node_set = set(nodes)
    for item in constraints:
        assert(item.lbound <= node_set)
        assert(item.ubound <= node_set)
        for scope in item.scopes:
            assert(scope.lbound <= node_set)
            assert(scope.ubound <= node_set)

    todo = constraints[:]
    while todo:
        items = []
        queue = [todo[0]]
        iset = set(queue) #set of items to skip when expanding connected component
        nset = set()
        parents = set()

        while queue:
            item = queue.pop()
            if item in frozen:
                parents.add(item)
                continue

            items.append(item)
            #list comprehension adds to iset as well to ensure uniqueness
            queue += [i2 for i2 in item.forcedup if not i2 in iset and not iset.add(i2)]
            queue += [i2 for i2 in item.forceddown if not i2 in iset and not iset.add(i2)]

            if not item.lbound.issubset(nset):
                assert(nset <= dset)
                nset |= item.lbound
                assert(nset <= dset)
                nset = dom.extend(nset)
                assert(nset <= dset)
                hits = [i2 for i2 in constraints if nset & i2.lbound]
                queue += [i2 for i2 in hits if not i2 in iset and not iset.add(i2)]

        assert(nset and nset == dom.extend(nset))
        #items is now a connected component
        candidates = [i for i in items if i.ubound.issuperset(nset)]
        candidates = [i for i in items if i.forcedup.issubset(frozen)]

        #make sure for each candidates that all of the nested items fall within a single scope
        cscope_assigns = []
        for cnode in candidates:
            svals = ddict(set)
            bad = False
            for item in items:
                if item is cnode:
                    continue

                scopes = [s for s in cnode.scopes if item.lbound & s.ubound]
                if len(scopes) != 1 or not scopes[0].ubound.issuperset(item.lbound):
                    bad = True
                    break
                svals[scopes[0]] |= item.lbound

            if not bad:
                cscope_assigns.append((cnode, svals))

        cnode, svals = cscope_assigns.pop() #choose candidate arbitrarily if more than 1
        assert(len(svals) <= len(cnode.scopes))
        for scope, ext in svals.items():
            scope.lbound |= ext
            assert(scope.lbound <= scope.ubound)
            assert(dom.extend(scope.lbound) == scope.lbound)

        cnode.lbound |= nset
        assert(cnode.lbound <= cnode.ubound)
        assert(cnode.lbound == (cnode.heads.union(*[s.lbound for s in cnode.scopes])))

        #find lowest parent
        parent = DummyParent
        while not parents.isdisjoint(children[parent]):
            temp = parents.intersection(children[parent])
            assert(len(temp) == 1)
            parent = temp.pop()

        if parent is not None:
            assert(cnode.lbound <= parent.lbound)

        children[parent].append(cnode)
        todo.remove(cnode)
        frozen.add(cnode)
        
    #make sure items are nested
    for k, v in children.items():
        temp = set()
        for child in v:
            assert(temp.isdisjoint(child.lbound))
            temp |= child.lbound
        assert(k is None or temp <= k.lbound)

    #Add a root so it is a tree, not a forest
    croot = FixedScopeCon(set(nodes))
    children[croot] = children[None]
    del children[None]
    return croot, children

def mergeExceptions(dom, children, constraints, nodes):
    parents = {}
    for k, cs in children.items():
        for child in cs:
            assert(child not in parents)
            parents[child] = k
    assert(set(parents) == set(constraints))

    def unforbid(forbidden, newdown):
        for n in newdown.lbound:
            if n in forbidden:
                forbidden[n] -= newdown.cset
                if not forbidden[n]:
                    del forbidden[n]

    def tryExtend(con, con2, removed):
        #Attempt to extend con to cover con2
        #If not successful, rollback the changes
        #though we may leave ubound smaller to help
        #fail earlier in the future
        assert(con.tag == con2.tag == 'try')
        assert(con.orig_target == con2.orig_target)
        forcedup = con.forcedup | con2.forcedup
        forceddown = con.forceddown | con2.forceddown
        assert(con not in forceddown)
        forcedup.discard(con)
        if forcedup & forceddown:
            return False

        body = con.lbound | con2.lbound
        for lower in forceddown:
            body |= lower.lbound
        body = dom.extend(body)

        oldparent = parent = parents[con]
        while not body.issubset(parent.lbound):
            body |= parent.lbound
            if not body.issubset(con.ubound):
                con.ubound &= parent.lbound
                return False
            parent = parents[parent]

        for child in children[parent]:
            if not child.lbound.isdisjoint(body):
                body |= child.lbound

        assert(body == dom.extend(body))
        if not body.issubset(con.ubound):
            return False
        for upper in forcedup: #Not ideal, but we do this for now to ensure the tree remains orderable
            if not body.issubset(upper.lbound):
                return False

        cset = con.cset | con2.cset
        forbidden = con.forbidden.copy()
        for newdown in (forceddown - con.forceddown):
            unforbid(forbidden, newdown)
        assert(all(forbidden.values()))

        for node in body:
            if node in forbidden and (cset & forbidden[node]):
                #The current cset is not compatible with the current partial order
                #Try to find some cons to force down in order to fix this
                bad = cset & forbidden[node]

                candidates = [c for c in trycons if c not in removed]
                candidates = [c for c in candidates if node in c.lbound and c.lbound.issubset(body)]
                candidates = [c for c in candidates if (c.cset & bad)]
                candidates = [c for c in candidates if c not in forcedup and c is not con]
                for topnd in candidates:
                    if topnd in forceddown:
                        continue

                    temp = topnd.forceddown - forceddown - removed
                    temp.add(topnd)
                    for newdown in temp:
                        unforbid(forbidden, newdown)
                    
                    assert(con not in temp)
                    forceddown |= temp
                    bad = cset & forbidden.get(node, ExceptionSet.EMPTY)
                    if not bad:
                        break
                if bad:
                    assert(cset - con.cset)
                    return False
        assert(forceddown.isdisjoint(forcedup))
        assert(all(forbidden.values()))

        #At this point, everything should be all right, so we need to update con and the tree
        con.lbound = body
        con.cset = cset
        con.forbidden = forbidden
        con.forcedup = forcedup
        con.forceddown = forceddown

        for new in con.forceddown:
            new.forcedup.add(con)
            new.forcedup |= forcedup

        for new in con.forcedup:
            unforbid(new.forbidden, con)
            for new2 in forceddown - new.forceddown - removed:
                unforbid(new.forbidden, new2)
            new.forceddown.add(con) 
            new.forceddown |= forceddown

        for child in children[con]:
            children[oldparent].append(child)
            assert(parents[child] == con)
            parents[child] = oldparent
        children[oldparent].remove(con)
        children[parent].append(con)
        parents[con] = parent

        newchildren = [c for c in children[parent] if c is not con and c.lbound.issubset(body)]
        for child in newchildren:
            children[parent].remove(child)
            assert(parents[child] == parent)
            parents[child] = con     
        children[con] = newchildren     

        for k,v in parents.items():
            assert(k != v)
            assert(k in children[v])
        return True

    topoorder = graph_util.topologicalSort(constraints, lambda cn:([parents[cn]] if cn in parents else []))
    trycons = [con for con in constraints if con.tag == 'try']
    # print 'Merging exceptions ({1}/{0}) trys'.format(len(constraints), len(trycons))
    trycons = sorted(trycons, key=topoorder.index)
    #note that the tree may be changed while iterating, but constraints should only move up 

    removed = set()
    for con in trycons:
        if con in removed:
            continue

        #First find the actual upper bound for the try scope
        #Nodes dominated by the tryblocks but not reachable from the catch target
        assert(len(con.lbound) == 1)
        tryhead = min(con.lbound)
        backnodes = dom.dominators(tryhead)
        catchreach = graph_util.topologicalSort([con.target], lambda node:[x for x in node.successors if x not in backnodes])
        con.ubound = set(nodes) - set(catchreach)

        #Now find which cons we can try to merge with
        candidates1 = [c for c in trycons if c not in removed and c.orig_target == con.orig_target]
        candidates2 = [c for c in candidates1 if c.lbound.issubset(con.ubound)]
        candidates2.remove(con)

        good = set()
        for con2 in candidates2:
            success = tryExtend(con, con2, removed)
            if success:
                good.add(con2)
                okdiff = set([con,con2])
        # print '{}/{} merged'.format(len(good), len(candidates2))

        #Now find which ones can be removed
        for con2 in candidates2:
            okdiff = set([con,con2])
            if not con2.lbound.issubset(con.lbound):
                continue
            if not con2.forceddown.issubset(con.forceddown | okdiff):
                continue
            if not con2.forcedup.issubset(con.forcedup | okdiff):
                continue
            if con2.cset - con.cset:
                continue
            assert(con2 in good)

            #now remove it
            removed.add(con2)
            for tcon in trycons:
                if tcon not in removed and tcon is not con:
                    assert(con in tcon.forceddown or con2 not in tcon.forceddown)
                    assert(con in tcon.forcedup or con2 not in tcon.forcedup)
                tcon.forcedup.discard(con2)
                tcon.forceddown.discard(con2)
            assert(con not in removed)

            parent = parents[con2]
            children[parent] += children[con2]
            for x in children[con2]:
                parents[x] = parent
            children[parent].remove(con2)
            del children[con2]
            del parents[con2]
        assert(good <= removed)

    #Cleanup
    removed_nodes = frozenset(c.target for c in removed)
    constraints = [c for c in constraints if c not in removed]
    trycons = [c for c in trycons if c not in removed]

    for con in constraints:
        con.lbound -= removed_nodes
        con.ubound -= removed_nodes
        for scope in con.scopes:
            scope.lbound -= removed_nodes
            scope.ubound -= removed_nodes

    for con in trycons:
        assert(not con.forcedup & removed)
        assert(not con.forceddown & removed)

        #For convienence, we were previously storing the try scope bounds in the main constraint bounds
        assert(len(con.scopes)==1)
        tryscope = con.scopes[0]
        tryscope.lbound = con.lbound.copy()
        tryscope.ubound = con.ubound.copy()
    # print 'Merging done'
    # print dict(collections.Counter(con.tag for con in constraints))

    #Now fix up the nodes. This is a little tricky
    nodes = [n for n in nodes if n not in removed_nodes]
    for node in nodes:
        node.predecessors = [x for x in node.predecessors if x not in removed_nodes]

        #start with normal successors and add exceptions back in
        node.successors = [x for x in node.successors if x in node.outvars]
        if node.eassigns:
            temp = {k.successors[0]:v for k,v in node.eassigns.items()}
            node.eassigns = ea = {}

            for con in trycons:
                if node in con.lbound and con.orig_target in temp:
                    ea[con.target] = temp[con.orig_target]
                    if node not in con.target.predecessors:
                        con.target.predecessors.append(node)
                    node.successors.append(con.target)
            assert(len(ea) >= len(temp))
        assert(removed_nodes.isdisjoint(node.successors))
    assert(dom.root not in removed_nodes)

    node_set = set(nodes)
    for item in constraints:
        assert(item.lbound <= node_set)
        assert(item.ubound <= node_set)
        for scope in item.scopes:
            assert(scope.lbound <= node_set)
            assert(scope.ubound <= node_set)

    #Regenerate dominator info to take removed nodes into account
    dom = DominatorInfo(dom.root)
    assert(set(dom._doms) == node_set)
    return dom, constraints, nodes

def fixTryConstraints(dom, constraints):
    #Add catchscopes and freeze other relations
    for con in constraints:
        if con.tag != 'try':
            continue

        lbound = set([con.target])
        ubound = dom.area(con.target)

        cscope = ScopeConstraint(lbound, ubound)
        con.scopes.append(cscope)

        #After this point, forced relations and cset are frozen
        #So if a node is forbbiden, we can't expand to it at all
        cset = con.cset
        tscope = con.scopes[0]

        empty = ExceptionSet.EMPTY
        tscope.ubound = set(x for x in tscope.ubound if not (cset & con.forbidden.get(x, empty)))
        del con.forbidden

        con.lbound = tscope.lbound | cscope.lbound
        con.ubound = tscope.ubound | cscope.ubound
        assert(tscope.lbound.issubset(tscope.ubound))
        assert(tscope.ubound.isdisjoint(cscope.ubound))

def _dominatorUBoundClosure(dom, lbound, ubound):
    #Make sure ubound is dominator closed
    #For now, we keep original dominator since the min cut stuff gets messed up otherwise
    udom = dom.dominator(lbound)
    ubound &= dom.area(udom)

    done = (ubound == lbound)
    while not done:
        done = True
        for x in list(ubound):
            if x == udom:
                continue
            for y in x.predecessors_nl:
                if y not in ubound:
                    done = False
                    ubound.remove(x)
                    break
    assert(ubound == dom.extend(ubound))
    assert(ubound.issuperset(lbound))
    assert(udom == dom.dominator(ubound))
    return ubound

def completeScopes(dom, croot, children):
    parentscope = {}
    for k, v in children.items():
        for child in v:
            pscopes = [scope for scope in k.scopes if child.lbound.issubset(scope.lbound)]
            assert(len(pscopes)==1)
            parentscope[child] = pscopes[0]

    nodeorder = graph_util.topologicalSort([dom.root], lambda n:n.successors_nl)
    nodeorder = {n:-i for i,n in enumerate(nodeorder)}

    stack = [croot]
    while stack:
        parent = stack.pop()

        #The problem is that when processing one child, we may want to extend it to include another child
        #We solve this by freezing already processed children and ordering them heuristically
        # TODO - find a better way to handle this
        revorder = sorted(children[parent], key=lambda cnode:(nodeorder[dom.dominator(cnode.lbound)], len(cnode.ubound)))
        frozen_nodes = set()

        while revorder:
            cnode = revorder.pop()
            if cnode not in children[parent]: #may have been made a child of a previously processed child
                continue

            scopes = [s for s in parent.scopes if s.lbound & cnode.lbound]
            assert(len(scopes)==1)

            ubound = cnode.ubound & scopes[0].lbound
            ubound -= frozen_nodes
            for other in revorder:
                if not ubound.issuperset(other.lbound):
                    ubound -= other.lbound

            assert(ubound.issuperset(cnode.lbound))
            ubound = _dominatorUBoundClosure(dom, cnode.lbound, ubound)
            body = cnode.lbound.copy()

            #Be careful to make sure the order is deterministic
            temp = set(body)
            parts = [n.norm_suc_nl for n in sorted(body, key=nodeorder.get)]
            startnodes = [n for n in itertools.chain(*parts) if not n in temp and not temp.add(n)]            

            temp = set(ubound)
            parts = [n.norm_suc_nl for n in sorted(ubound, key=nodeorder.get)]
            endnodes = [n for n in itertools.chain(*parts) if not n in temp and not temp.add(n)]

            #Now use Edmonds-Karp, modified to find min vertex cut
            startset = frozenset(startnodes)
            endset = frozenset(endnodes)
            used = set()
            backedge = {}

            #lastseen assigned in loop
            while 1:
                #Find augmenting path via BFS
                queue = collections.deque([(n,True,(n,)) for n in startnodes if n not in used])

                seen = set()
                augmenting_path = None
                while queue:
                    pos, lastfw, path = queue.popleft()
                    seen.add(pos)

                    if pos in used:
                        if pos not in startset:
                            pos2 = backedge[pos]
                            queue.append((pos2, False, path+(pos2,)))
                        if not lastfw and pos not in endset: #last edge was backwards, so we're allowed to go forwards
                            for pos2 in pos.norm_suc_nl:
                                if pos2 not in path: #avoid cycles to avoid cluttering up the queue
                                    queue.append((pos2, True, path+(pos2,)))
                    else:
                        assert(lastfw)
                        if pos in endset: #success!
                            augmenting_path = path
                            break
                        else:
                            for pos2 in pos.norm_suc_nl:
                                if pos2 not in path: #avoid cycles to avoid cluttering up the queue
                                    queue.append((pos2, True, path+(pos2,)))
                else: #queue is empty but we didn't find anything
                    assert(augmenting_path is None)   
                    lastseen = seen | (startset & used)
                    break

                path = augmenting_path
                assert(path[0] in startset and path[-1] in endset)

                last = None
                for pos in path:
                    if last in pos.norm_suc_nl:
                        assert(pos in used)
                        assert(backedge[pos] != last)
                    else:
                        used.add(pos)
                        backedge[pos] = last
                        assert((backedge[pos] is None) == (pos in startset))
                    last = pos  

            #Now we have the max flow, try to find the min cut
            #Just use the set of nodes visited during the final BFS
            interior = [x for x in (lastseen & ubound) if lastseen.issuperset(x.norm_suc_nl)]
            cutsize = len(lastseen)-len(interior)
            assert(cutsize <= min(len(startset), len(used)))

            body0 = body.copy()
            body.update(interior)
            body = dom.extend(body) #TODO - figure out a cleaner way to do this
            assert(body.issubset(ubound) and body==dom.extend(body))
            #The new cut may get messed up by the inclusion of extra children. But this seems unlikely
            newchildren = []
            for child in revorder:
                if child.lbound & body:
                    body |= child.lbound
                    newchildren.append(child)

            assert(body.issubset(ubound) and body == dom.extend(body))
            cnode.lbound = body
            for scope in cnode.scopes:
                scope.lbound |= (body & scope.ubound)

            children[cnode].extend(newchildren)
            children[parent] = [c for c in children[parent] if c not in newchildren]
            frozen_nodes |= body

        #Note this is only the immediate children, after some may have been moved down the tree during previous processing
        stack.extend(children[parent])

class _mnode(object):
    def __init__(self, head):
        self.head = head
        self.nodes = set()
        self.items = []
        #children top selected subtree depth

    def __str__(self): return 'M'+str(self.head)[3:]
    __repr__ = __str__

def _addBreak_sub(dom, rno_get, body, childcons):
    # Create dom* tree
    # This is a subset of dominators that dominate all nodes reachable from themselves
    domC = {n:dom.dominators(n) for n in body}
    for n in sorted(body, key=rno_get): #reverse topo order
        for n2 in n.successors_nl:
            if n2 not in body:
                continue
            match = len([x for x,y in zip(domC[n], domC[n2]) if x==y])
            assert(match and domC[n][:match] == domC[n2][:match])
            domC[n] = domC[n][:match]

    heads = set(n for n in body if domC[n][-1] == n)
    for n in body: 
        domC[n] = [x for x in domC[n] if x in heads]

    #Make sure this is deterministicly ordered
    mdata = collections.OrderedDict((k,_mnode(k)) for k in sorted(heads, key=rno_get))
    for n in body:
        mdata[domC[n][-1]].nodes.add(n)
    for item in childcons:
        head = domC[dom.dominator(item.lbound)][-1] 
        mdata[head].items.append(item)
        mdata[head].nodes |= item.lbound

    # Now merge nodes until they no longer cross item boundaries
    for h in heads:
        if h not in mdata:
            continue

        hits = mdata[h].nodes.intersection(mdata)
        while len(hits) > 1:
            hits.remove(h)
            for h2 in hits:
                assert(h in domC[h2] and h2 not in domC[h])
                mdata[h].nodes |= mdata[h2].nodes
                mdata[h].items += mdata[h2].items
                del mdata[h2]
            hits = mdata[h].nodes.intersection(mdata)
        assert(hits == set([h]))
    
    #Now that we have the final set of heads, fill in the tree data
    #add a dummy to the front so [-1] always works
    domPruned = {h:[None]+[h2 for h2 in domC[h][:-1] if h2 in mdata] for h in mdata}

    for h, mnode in mdata.items():
        mnode.top = True
        mnode.selected = [mnode]
        mnode.subtree = [mnode]
        #Note, this is max nesting depth, NOT depth in the tree
        mnode.depth = 1 if mnode.items else 0
        if any(item.tag == 'switch' for item in mnode.items):
            mnode.depth = 2
        mnode.tiebreak = rno_get(h)

        assert(h in mnode.nodes and len(mnode.nodes) >= len(mnode.items))      
        mnode.children = [mnode2 for h2, mnode2 in mdata.items() if domPruned[h2][-1] == h]

    revorder = graph_util.topologicalSort(mdata.values(), lambda mn:mn.children)
    assert(len(revorder) == len(mdata))
    assert(sum(len(mn.children) for mn in revorder) == len(revorder)-1)

    #Now partition tree into subtrees, trying to minimize max nesting
    for mnode in revorder:
        if mnode.children:
            successor = max(mnode.children, key=lambda mn:(mn.depth, len(mn.subtree), mn.tiebreak))

            depths = sorted(mn.depth for mn in mnode.children)
            temp = max(d-i for i,d in enumerate(depths))
            mnode.depth = max(mnode.depth, temp+len(mnode.children)-1)

            for other in mnode.children:
                if other is successor:
                    continue
                other.top = False
                mnode.selected += other.subtree
            mnode.subtree = mnode.selected + successor.subtree
            for subnode in mnode.selected[1:]:
                subnode.top = False
        assert(mnode.top)
        assert(len(set(mnode.subtree)) == len(mnode.subtree))
    
    results = []
    for root in revorder:
        if not root.top:
            continue
        nodes, items = set(), []
        for mnode in root.selected:
            nodes |= mnode.nodes
            items += mnode.items
        results.append((nodes, items))
    
    temp = list(itertools.chain.from_iterable(zip(*results)[1]))
    assert(len(temp) == len(childcons) and set(temp) == set(childcons))
    return results

def addBreakScopes(dom, croot, constraints, children):
    nodeorder = graph_util.topologicalSort([dom.root], lambda n:n.successors_nl)
    nodeorder = {n:i for i,n in enumerate(nodeorder)}
    rno_get = nodeorder.get #key for sorting nodes in rev. topo order

    stack = [croot]
    while stack:
        cnode = stack.pop()
        oldchildren = children[cnode][:]
        newchildren = children[cnode] = []

        for scope in cnode.scopes:
            subcons = [c for c in oldchildren if c.lbound <= scope.lbound]

            results = _addBreak_sub(dom, rno_get, scope.lbound, subcons)
            results = [t for t in results if len(t[0]) > 1]

            for nodes, items in results:
                assert(dom.extend(nodes) == nodes)
                if len(items) == 1 and items[0].lbound == nodes:
                    new = items[0] #no point wrapping it in a scope if it already has identical body
                else:
                    new = FixedScopeCon(nodes)
                    constraints.append(new)
                    children[new] = items
                newchildren.append(new)
                stack.append(new)
        _checkNested(children)

def constraintsToSETree(dom, croot, children, nodes):
    seitems = {n:SEBlockItem(n) for n in nodes} #maps entryblock -> item

    #iterate over tree in reverse topological order (bottom up)
    revorder = graph_util.topologicalSort([croot], lambda cn:children[cn])
    for cnode in revorder:
        sescopes = []
        for scope in cnode.scopes:
            body = scope.lbound
            pos = dom.dominator(body)
            items = []
            while pos is not None:
                item = seitems[pos]
                del seitems[pos]
                items.append(item)
                suc = [n for n in item.successors if n in body]
                assert(len(suc) <= 1)
                pos = suc[0] if suc else None

            newscope = SEScope(items)
            sescopes.append(newscope)
            assert(newscope.nodes == frozenset(body))

        if cnode.tag in ('if','switch'):
            head = seitems[cnode.head]
            assert(isinstance(head, SEBlockItem))
            del seitems[cnode.head]

        new = None
        if cnode.tag == 'while':
            new = SEWhile(sescopes[0])
        elif cnode.tag == 'if':
            #ssa_jump stores false branch first, but ast gen assumes true branch first
            sescopes = [sescopes[1], sescopes[0]]
            new = SEIf(head, sescopes)            
        elif cnode.tag == 'switch':
            #Switch fallthrough can only be done implicitly, but we may need to jump to it
            #from arbitrary points in the scope, so we add an extra scope so we have a 
            #labeled break. If unnecessary, it should be removed later on anyway
            sescopes = [SEScope([sescope]) for sescope in sescopes]
            new = SESwitch(head, sescopes)            
        elif cnode.tag == 'try':
            catchtts = cnode.cset.getTopTTs()
            catchvar = cnode.catchvar
            new = SETry(sescopes[0], sescopes[1], catchtts, catchvar)
        elif cnode.tag == 'scope':
            new = sescopes[0]

        assert(new.nodes == frozenset(cnode.lbound))
        assert(new.entryBlock not in seitems)
        seitems[new.entryBlock] = new

    assert(len(seitems) == 1)
    assert(isinstance(seitems.values()[0], SEScope))
    return seitems.values()[0]

def _checkNested(ctree_children):
    #Check tree for proper nesting
    for k, children in ctree_children.items():
        for child in children:
            assert(child.lbound <= k.lbound)    
            assert(child.lbound <= child.ubound)  
            scopes = [s for s in k.scopes if s.ubound & child.lbound]
            assert(len(scopes) == 1)

            for c1, c2 in itertools.combinations(child.scopes, 2):
                assert(c1.lbound.isdisjoint(c2.lbound))
                assert(c1.ubound.isdisjoint(c2.ubound))

        for c1, c2 in itertools.combinations(children, 2):
            assert(c1.lbound.isdisjoint(c2.lbound))

def structure(entryNode, nodes):
    for n in nodes:
        for x in n.predecessors:
            assert(n in x.successors)        
        for x in n.successors:
            assert(n in x.predecessors)                        
        assert(set(n.successors) == (set(n.outvars) | set(n.eassigns)))

    #eliminate self loops
    for n in nodes[:]:
        if n in n.successors:
            nodes.append(n.indirectEdges([n]))

    for n in nodes:
        for x in n.predecessors:
            assert(n in x.successors)        
        for x in n.successors:
            assert(n in x.predecessors)                        
        assert(set(n.successors) == (set(n.outvars) | set(n.eassigns)))

    #note, these add new nodes (list passed by ref)
    while_heads = structureLoops(nodes)
    newtryinfos = structureExceptions(nodes)
    switchinfos, ifinfos = structureConditionals(entryNode, nodes)
    dom = DominatorInfo(entryNode) #no new nodes should be created, so we're free to keep dom info around
    constraints = createConstraints(dom, while_heads, newtryinfos, switchinfos, ifinfos)

    croot, ctree_children = orderConstraints(dom, constraints, nodes)

    #May remove nodes (and update dominator info)
    dom, constraints, nodes = mergeExceptions(dom, ctree_children, constraints, nodes)

    #TODO - parallelize exceptions

    fixTryConstraints(dom, constraints)

    #After freezing the try constraints we need to regenerate the tree
    croot, ctree_children = orderConstraints(dom, constraints, nodes)

    # for n in nodes:
    #     print n, [x for x in n.successors if x in n.outvars], [x for x in n.successors if x not in n.outvars]

    #now that no more nodes will be changed, create lists of backedge free edges
    for n in nodes:
        temp = set(dom.dominators(n))
        temp2 = dom.area(n)
        n.successors_nl = [x for x in n.successors if x not in temp]
        n.predecessors_nl = [x for x in n.predecessors if x not in temp2]
        n.norm_suc_nl = [x for x in n.successors_nl if x in n.outvars]
    for n in nodes:
        for n2 in n.successors_nl:
            assert(n in n2.predecessors_nl)
        for n2 in n.predecessors_nl:
            assert(n in n2.successors_nl)

    # print 'completing scopes'
    _checkNested(ctree_children)
    completeScopes(dom, croot, ctree_children)

    # print 'adding breaks'
    _checkNested(ctree_children)
    addBreakScopes(dom, croot, constraints, ctree_children)
    _checkNested(ctree_children)

    return constraintsToSETree(dom, croot, ctree_children, nodes)
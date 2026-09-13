# coding=utf-8

import time

from xml.dom import minidom as _minidom

from Codec import _u2
import Guard
import Manifest
import Paths
import Resources
import Validate
from Actions import applyAction, evaluateGuards
from Logger import logInfo, logError
import Planner
from Planner import (
    discoverManifests, summarizePlan, topoSort, unboundOwnedTargets,
    validateFileReferences, validateRequirements, validateTargets,
)
from Transaction import Transaction

class _Stats(object):
    def __init__(self):
        self.discovered = 0
        self.installed = 0
        self.updated = 0
        self.unchanged = 0
        self.skipped = 0
        self.failed = 0
        self.removed = 0
        self.definitions = 0
        self.definitionsNew = 0
        self.definitionsDropped = 0
        self.conflicts = 0

def runInstaller(installerVersion):
    stats = _Stats()
    Paths.ensureDir(Paths.cacheDir())

    registry = _loadRegistry()
    if registry.get('buildId') and registry['buildId'] != Paths.gameBuildId():
        logInfo('game build changed (%s -> %s); flushing pristine cache'
                % (registry['buildId'], Paths.gameBuildId()))
        Resources.invalidateCache()

    manifests = discoverManifests()
    stats.discovered = len(manifests)
    wasCompiled = registry.get('compiled', {})
    recordedStamps = registry.get('stamps', {})
    recordedOutputs = registry.get('outputs', {})
    if not manifests:
        _dropOrphanedCompiles(wasCompiled, {})
        tx = Transaction()
        _revertOrphanedOutputs(recordedOutputs, set(), tx)
        try:
            tx.commit()
        except Exception as exc:
            logError('transaction commit failed: %s' % exc)
        Validate.removeStubs()
        return _finalize(registry, [], stats, installerVersion)

    newHashes = dict((m.modName, m.sourceHash) for m in manifests)
    oldHashes = registry.get('mods', {})
    changed = newHashes != oldHashes
    buildChanged = registry.get('buildId') != Paths.gameBuildId()

    eligible = validateRequirements(manifests, installerVersion)
    # Before anything is built: a mod that writes what Unbound owns cannot
    # work, and its payload would otherwise be generated and then ignored.
    owned = unboundOwnedTargets()
    eligible = [m for m in eligible if validateTargets(m, owned)]
    # Sorted BEFORE anything is built: definitions merge in this order, and a
    # dict's iteration order is the mod names' hashes.
    eligible = topoSort(eligible)
    # Payloads commit first: reference validation and the compiler both read
    # them off disk. revertCommitted below undoes them if the registration
    # that names them never lands -- an XML registered against a SWF missing
    # its keys is a client that refuses to boot.
    payloadTx = Transaction()
    (compiled, compileFailed, declared, sources, registration,
     definitionApplied) = _runBuilds(eligible, wasCompiled, recordedStamps,
                                     payloadTx, stats)
    try:
        payloadTx.commit()
    except Exception as exc:
        logError('payload commit failed: %s' % exc)
        Resources.shutdown()
        return stats

    builtChanged = compiled != wasCompiled
    # Before the early return, not after: an output clobbered by another
    # installer is exactly the case where nothing else has changed, and the
    # rebuild below is what repairs it.
    drift = Guard.detectDrift(recordedOutputs, recordedStamps)
    _reportDrift(drift)
    if not changed and not buildChanged and not builtChanged and not drift:
        logInfo('no manifest changes since last run; nothing to do')
        stats.unchanged = len(manifests)
        _dropOrphanedCompiles(wasCompiled, declared)
        return stats
    if not changed and not buildChanged and not builtChanged and drift:
        logInfo('manifests unchanged but an output drifted; re-applying')
    if not changed and buildChanged:
        logInfo('manifests unchanged but build moved; re-applying')
    if not changed and not buildChanged and builtChanged:
        logInfo('manifests unchanged but a compiled payload moved; re-applying')

    removedNames = [name for name in oldHashes if name not in newHashes]
    stats.removed = len(removedNames)
    for name in removedNames:
        logInfo("removed '%s' since last run; will revert its changes" % name)

    eligible = [m for m in eligible if m.modName not in compileFailed]
    eligible = [m for m in eligible if validateFileReferences(m)]
    ordered = topoSort(eligible)
    summarizePlan(ordered)
    stats.failed = len(compileFailed)
    stats.skipped = stats.discovered - len(ordered) - len(compileFailed)

    # Seeded, not empty: a mod whose only output is a definition never
    # touches a <build> target, so without this it lands in no bucket at all
    # and the summary reports it as having done nothing.
    applied = set(definitionApplied)
    failed = set()
    forgeFailed = set()
    contributors = [(m.modName, m.builds, applied, failed) for m in ordered]
    if registration is not None:
        contributors.append((FORGE, [registration], set(), forgeFailed))

    targetFiles = _collectTargetFiles(contributors)
    tx = Transaction()
    _revertOrphanedOutputs(recordedOutputs, set(targetFiles), tx)
    staged = []

    for relPath in targetFiles:
        try:
            updated = _applyToTarget(relPath, contributors, sources)
        except _TargetSkipped as skip:
            logError("target '%s' skipped: %s" % (relPath, skip))
            continue
        except Exception as exc:
            logError("target '%s' skipped: %s: %s"
                     % (relPath, type(exc).__name__, exc))
            continue
        if updated is None:
            continue
        absPath = Paths.resolveResModsTarget(relPath)
        if absPath is None:
            logError("target path escapes res_mods/: %s" % relPath)
            continue
        tx.stage(absPath, updated)
        staged.append((relPath, updated))

    if forgeFailed:
        logError('the definitions were built but could not be registered in '
                 '%s; the client will not load them' % Manifest.USS_SETTINGS)

    for m in ordered:
        if m.modName in failed:
            stats.failed += 1
        elif m.modName in applied:
            if oldHashes.get(m.modName) is None:
                stats.installed += 1
            elif oldHashes.get(m.modName) != m.sourceHash:
                stats.updated += 1
            else:
                stats.unchanged += 1

    try:
        tx.commit()
    except Exception as exc:
        logError('transaction commit failed: %s' % exc)
        payloadTx.revertCommitted()
        Resources.shutdown()
        return stats

    # After the commit, never before: a file pruned while uss_settings still
    # names it is the registered-but-absent entry that stalls the boot, and a
    # run that fails between the two leaves exactly that.
    _dropOrphanedCompiles(wasCompiled, declared)

    successful = [m for m in ordered if m.modName not in failed]
    return _finalize(registry, successful, stats, installerVersion,
                     Guard.outputHashes(staged), compiled)

FORGE = 'ModForge'

class _TargetSkipped(Exception):
    pass

def _reportDrift(drift):
    """ModForge owns its targets and rebuilds them from pristine, so a foreign
    edit is about to be discarded. Keep a copy first: the likeliest author of
    one is the mod author, hand-editing during development."""
    for relPath, why in drift:
        logError("'%s' changed on disk since our last run (%s); rebuilding it "
                 "from pristine. To keep an edit to this file, declare it in a "
                 "blueprint -- ModForge rewrites it on every run."
                 % (relPath, why))
        absPath = Paths.resolveResModsTarget(relPath)
        if absPath is not None and Paths.fileExists(absPath):
            saved = _backupDrifted(relPath, absPath)
            if saved:
                logInfo('kept the drifted copy at %s' % saved)

def _backupDrifted(relPath, absPath):
    stamp = '%d' % int(time.time())
    dest = Paths.cacheDir() + 'drift_backups/' + stamp + '/' + relPath
    try:
        Paths.writeBytes(dest, Paths.readBytes(absPath))
    except Exception as exc:
        logError('cannot back up %s: %s' % (relPath, exc))
        return None
    return dest

def _runBuilds(manifests, recorded, stamps, tx, stats):
    import Fragment
    sources = Fragment.Sources()
    built = {}
    failedNames = set()
    declared = set()
    # absPath -> staged bytes, so a compile can read a payload generated in
    # this same run, before any of it has reached disk.
    pending = {}
    emittedXml = []
    for m in manifests:
        for spec in m.builds:
            if not spec.root:
                continue
            declared.add(spec.file)
            try:
                built[spec.file] = _runOneGenerated(m, spec, sources,
                                                    recorded, stamps, tx,
                                                    pending, emittedXml)
            except Exception as exc:
                logError("'%s' cannot generate %s: %s"
                         % (m.modName, spec.file, exc))
                failedNames.add(m.modName)

    survivors = [m for m in manifests if m.modName not in failedNames]
    definitionApplied = set()
    try:
        registration = _runDefinitions(survivors, sources, recorded, stamps,
                                       tx, pending, built, declared,
                                       failedNames, emittedXml, stats,
                                       definitionApplied)
    except Exception as exc:
        # Nothing registered beats a traceback that installs no mod at all.
        logError('the definitions could not be built (%s: %s); none of them '
                 'are registered' % (type(exc).__name__, exc))
        registration = None

    for problem in Validate.duplicateDefinitions(emittedXml):
        logError(problem)
    for problem in _styleProblems(emittedXml, sources):
        logError(problem)
    return (built, failedNames, declared, sources, registration,
            definitionApplied)

def _styleProblems(emittedXml, sources):
    """Gated on a use existing: resolving needs the vanilla styles index,
    and a run that emits no `<styleClass>` should not pay for building it."""
    if not [1 for _rel, data in emittedXml if Validate.styleClassUses(data)]:
        return []
    try:
        vanilla = sources.index(Manifest.VANILLA_STYLES, 'css', 'name')
    except Exception as exc:
        return ['cannot check style references: %s' % exc]
    return Validate.unresolvedStyleClasses(emittedXml, vanilla)

class _Definition(object):
    __slots__ = ('namespace', 'name', 'relPath', 'absPath', 'data', 'isNew',
                 'contributors')

def _runDefinitions(manifests, sources, recorded, stamps, tx, pending, built,
                    declared, failedNames, emittedXml, stats,
                    definitionApplied):
    """One XML per definition merged across every mod that names it, and one
    shared SWF over all of them. Returns what to register, or None."""
    import Definitions
    emitted, failed, stats.conflicts = _mergeDefinitions(manifests, sources)
    failedNames |= failed
    if not emitted:
        return None

    created = 0
    paths = []
    for d in emitted:
        created += d.isNew
        pending[d.absPath] = d.data
        paths.append(d.absPath)
        logInfo('%s %s, from %s'
                % ('created' if d.isNew else 'overrode',
                   Definitions.label(d.namespace, d.name),
                   ', '.join(d.contributors)))
    logInfo('%d definition(s): %d overridden, %d created'
            % (len(emitted), len(emitted) - created, created))

    dropped = set()
    swf, count = _compileDefinitions(paths, pending, dropped)
    kept = _coveredByTheSwf(emitted, dropped, pending)
    for absPath in dropped:
        del pending[absPath]
    stats.definitions = len(kept)
    stats.definitionsNew = len([1 for d in kept if d.isNew])
    stats.definitionsDropped = len(emitted) - len(kept)
    for d in kept:
        declared.add(d.relPath)
        emittedXml.append((d.relPath, d.data))
        definitionApplied.update(d.contributors)
        _stageDefinition(d, recorded, stamps, tx, built)

    if not kept:
        return None
    swfPath = None
    if count:
        _stageDefinitionsSwf(swf, [d.absPath for d in kept], pending,
                             recorded, tx, built, declared)
        swfPath = Manifest.USS_DEFINITIONS_SWF
    return Manifest.registrationBuild(
        [Manifest.ussDefinitionPath(d.namespace, d.name) for d in kept],
        swfPath)

def _coveredByTheSwf(emitted, dropped, pending):
    """Which definitions may be registered: the ones whose every expression
    key is in the SWF this run compiled.

    A key the SWF lacks is not caught at load -- `UbNativeExpression` stores
    null and `eval` CALLS it, so it is a #1006 on whatever screen first
    builds that block. This is the one gate: what the compile rejected has no
    keys in the SWF, so it fails here too."""
    import UssCompile
    covered = UssCompile.expressionKeys(
        [d.absPath for d in emitted if d.absPath not in dropped], pending)
    out = []
    for d in emitted:
        try:
            missing = UssCompile.expressionKeys([d.absPath], pending) - covered
            why = '%d expression(s) the compiled SWF does not carry' % len(
                missing)
        except Exception as exc:
            missing, why = True, 'its expressions cannot be read back: %s' % exc
        if missing:
            logError('%s: %s; not registering it rather than shipping a block '
                     'that throws when it is built' % (d.relPath, why))
            dropped.add(d.absPath)
            continue
        out.append(d)
    return out

def _mergeDefinitions(manifests, sources):
    """(emitted, failedNames, refusedWrites), re-merged until the failed set
    is stable.

    A mod dropped over one definition must not stay applied in another, and
    a failure is only known once its actions have run."""
    import Definitions
    failed = set()
    while True:
        merger = Definitions.Merger(sources)
        emitted = []
        roundFailed = set()
        contributing = [m for m in manifests if m.modName not in failed]
        for key, contributions in Definitions.collect(contributing):
            namespace, name = key
            relPath = Manifest.definitionFile(namespace, name)
            absPath = Paths.resolveResModsTarget(relPath)
            if absPath is None:
                logError('%s: output path escapes res_mods/: %s'
                         % (Definitions.label(namespace, name), relPath))
                continue
            landed = set()
            try:
                data, isNew = merger.build(key, contributions, landed,
                                           roundFailed)
            except Exception as exc:
                logError('cannot assemble %s: %s: %s'
                         % (Definitions.label(namespace, name),
                            type(exc).__name__, exc))
                roundFailed.update(m.modName for m, _ in contributions)
                continue
            if data is not None:
                d = _Definition()
                (d.namespace, d.name, d.relPath, d.absPath, d.data,
                 d.isNew) = namespace, name, relPath, absPath, data, isNew
                d.contributors = [m.modName for m, _ in contributions
                                  if m.modName in landed]
                emitted.append(d)
        if not roundFailed:
            return emitted, failed, len(merger.refused)
        failed |= roundFailed

def _compileDefinitions(paths, pending, dropped):
    """One SWF over every definition. A definition whose expressions do not
    parse is dropped rather than costing every other one its keys."""
    import UssCompile
    try:
        return UssCompile.compileMarkup(paths, pending, allowEmpty=True)
    except Exception as exc:
        logError('the definitions do not compile as one (%s); compiling each '
                 'to find which' % exc)
    good = []
    for absPath in paths:
        try:
            UssCompile.compileMarkup([absPath], pending, allowEmpty=True)
        except Exception as exc:
            logError('%s: dropped, its expressions do not compile: %s'
                     % (absPath, exc))
            dropped.add(absPath)
            continue
        good.append(absPath)
    if not good:
        return None, 0
    try:
        return UssCompile.compileMarkup(good, pending, allowEmpty=True)
    except Exception as exc:
        logError('the definitions still do not compile with the %d bad one(s) '
                 'out; none are registered: %s' % (len(dropped), exc))
        dropped.update(good)
        return None, 0

def _stageDefinition(d, recorded, stamps, tx, built):
    stamp = Paths.hashBytes(d.data)
    built[d.relPath] = (stamp, ', '.join(d.contributors))
    previous = recorded.get(d.relPath)
    if (previous and previous[0] == stamp
            and Guard.stampHolds(d.relPath, stamps)):
        return
    if Paths.hashFile(d.absPath) != stamp:
        tx.stage(d.absPath, d.data)

def _stageDefinitionsSwf(swf, sourcePaths, pending, recorded, tx, built,
                         declared):
    relPath = Manifest.DEFINITIONS_SWF
    declared.add(relPath)
    absPath = Paths.resolveResModsTarget(relPath)
    stamp = Paths.hashBytes(''.join(
        [_COMPILER_STAMP] + [_sourceHash(p, pending) for p in sourcePaths]))
    built[relPath] = (stamp, 'definitions')
    previous = recorded.get(relPath)
    if previous and previous[0] == stamp and Paths.fileExists(absPath):
        return
    tx.stage(absPath, str(swf))

def _runOneGenerated(m, spec, sources, recorded, stamps, tx, pending,
                     emittedXml):
    import Build
    outPath = Paths.resolveResModsTarget(spec.file)
    if outPath is None:
        raise Exception('output path escapes res_mods/: %s' % spec.file)
    for rel in Build.sourceFiles(spec.actions):
        if Paths.resolveResModsTarget(rel) is None:
            raise Exception('source path escapes res_mods/: %s' % rel)

    data = Build.buildDocument(spec, m.modName, sources)
    stamp = Paths.hashBytes(data)

    # Skips re-reading and re-hashing the output; does NOT skip the rebuild.
    # A vanilla source can change without the build id moving (that is what
    # test_a_changed_vanilla_block_regenerates_and_recompiles pins), so the
    # document has to be built to know whether it still matches.
    pending[outPath] = data
    emittedXml.append((spec.file, data))
    previous = recorded.get(spec.file)
    if (previous and previous[0] == stamp and Guard.stampHolds(spec.file, stamps)):
        return (stamp, m.modName)

    # Staged only when it actually differs: rewriting an identical file moves
    # its mtime and costs the stat gate its fast path on the next run.
    if Paths.hashFile(outPath) != stamp:
        tx.stage(outPath, data)
        logInfo("'%s' generated %s from %d instruction(s)"
                % (m.modName, spec.file, len(spec.actions)))
    return (stamp, m.modName)

def _sourceHash(absPath, pending):
    if absPath in pending:
        return Paths.hashBytes(pending[absPath])
    return Paths.hashFile(absPath)

def _revertOrphanedOutputs(recordedOutputs, claimedPaths, tx):
    """A target no surviving mod claims goes back to stock content. Restoring
    rather than deleting: the file keeps existing, so no res_mods entry is
    left pointing at nothing."""
    reverted = []
    for relPath in sorted(recordedOutputs):
        if relPath in claimedPaths:
            continue
        absPath = Paths.resolveResModsTarget(relPath)
        if absPath is None:
            continue
        pristine = Resources.loadPristine(relPath)
        if pristine is None:
            logError('cannot restore %s: no pristine copy' % relPath)
            continue
        if Paths.fileExists(absPath) and Paths.readBytes(absPath) == pristine:
            reverted.append(relPath)
            continue
        try:
            tx.stage(absPath, pristine)
        except Exception as exc:
            logError('cannot restore %s: %s' % (relPath, exc))
            continue
        reverted.append(relPath)
        logInfo('no mod edits %s any more; restoring the stock file' % relPath)
    return reverted

def _dropOrphanedCompiles(recorded, declaredPaths):
    for relPath in sorted(recorded):
        if relPath in declaredPaths:
            continue
        absPath = Paths.resolveResModsTarget(relPath)
        if absPath is None or not Paths.fileExists(absPath):
            continue
        try:
            Paths.removeFile(absPath)
        except Exception as exc:
            logError('cannot remove %s: %s' % (relPath, exc))
            continue
        logInfo("removed %s; '%s' no longer builds it"
                % (relPath, recorded[relPath][1]))

def _collectTargetFiles(contributors):
    seen = []
    seenSet = set()
    for _label, builds, _applied, _failed in contributors:
        for t in builds:
            if t.root:
                continue
            if t.file not in seenSet:
                seenSet.add(t.file)
                seen.append(t.file)
    return seen

def _applyToTarget(relPath, contributors, sources):
    """`contributors` is (label, builds, appliedOut, failedOut) in apply
    order. Forge's own entries ride in as one of them, with sets of its own
    so its name can never be confused with a mod's."""
    pristine = Resources.loadPristine(relPath)
    if pristine is None:
        raise _TargetSkipped('cannot fetch pristine copy')

    try:
        doc = _minidom.parseString(pristine)
    except Exception as exc:
        raise _TargetSkipped('pristine is not valid XML: %s' % exc)

    mutated = False
    for label, builds, appliedOut, failedOut in contributors:
        targets = [t for t in builds
                   if not t.root and t.file == relPath]
        if not targets:
            continue

        snapshot = doc.cloneNode(True)
        try:
            edited = False
            for tspec in targets:
                if not evaluateGuards(doc.documentElement, tspec.guards):
                    logInfo("'%s' guard blocks edits to %s"
                            % (label, relPath))
                    continue
                for action in tspec.actions:
                    logInfo("'%s': %s on %s"
                            % (label, action.kind, relPath))
                    if applyAction(doc, action, label, None, sources):
                        edited = True

            if edited:
                mutated = True
                appliedOut.add(label)
        except Exception as exc:
            logError("'%s' failed on %s: %s: %s"
                     % (label, relPath, type(exc).__name__, exc))
            failedOut.add(label)

            doc.unlink()
            doc = snapshot
            continue
        else:
            snapshot.unlink()

    if not mutated:
        return None
    _guardDocument(relPath, doc)
    return _serialize(doc)

def _guardDocument(relPath, doc):
    resolve = Planner.resolveReference

    stubPathFor = lambda tag: (Validate.ensureXmlStub() if tag == 'xmlfile'
                               else Validate.ensureSwfStub())
    for original, action in Validate.substituteBrokenRefs(
            doc, relPath, resolve, stubPathFor):
        if action == 'removed':
            logError("'%s' would not load; entry removed so the client boots "
                     "with that mod inert" % original)
        else:
            logError("'%s' would not load; redirected to %s so the load "
                     "completes and that mod alone is inert"
                     % (original, action))

    problems = Validate.validateAssembled(relPath, doc, resolve)
    problems.extend(
        Validate.validateElementNames(doc, Validate.unbound2ElementNames()))
    for problem in problems:
        logError('%s: %s' % (relPath, problem))
    return problems

def _serialize(doc):
    pretty = doc.toprettyxml(indent='\t')
    lines = []
    for line in pretty.split('\n'):
        if line.strip():
            lines.append(line)
    out = '\n'.join(lines)

    if not out.startswith('<?xml'):
        out = '<?xml version="1.0" ?>\n' + out
    if isinstance(out, unicode):
        # minidom hands back unicode; the target is opened 'wb', so anything
        # above ASCII would raise on write and hash in a different domain
        # from the same file read back. Mirrors Build.serialize.
        out = out.encode('utf-8')
    return out

def _loadRegistry():
    p = Paths.installedRegistryPath()
    if not Paths.fileExists(p):
        return {'buildId': None, 'mods': {}}
    try:
        root = _u2.fromstring(Paths.readBytes(p))
    except Exception as exc:
        logError('installed.xml is unreadable (%s); treating as first run' % exc)
        return {'buildId': None, 'mods': {}}
    mods = {}
    for child in root.findall('mod'):
        name = child.get('name')
        h = child.get('hash')
        if name and h:
            mods[name] = h
    outputs = {}
    for child in root.findall('output'):
        path = child.get('path')
        h = child.get('hash')
        if path and h:
            outputs[path] = h
    compiled = {}
    for child in root.findall('compiled'):
        path = child.get('path')
        h = child.get('hash')
        if path and h:
            compiled[path] = (h, child.get('mod') or '')
    stamps = {}
    for child in root.findall('stamp'):
        path = child.get('path')
        size = child.get('size')
        mtime = child.get('mtime')
        if path and size is not None and mtime is not None:
            stamps[path] = (size, mtime)
    return {
        'buildId': root.get('buildId'),
        'mods': mods,
        'outputs': outputs,
        'compiled': compiled,
        'stamps': stamps,
    }

def _saveRegistry(buildId, successfulManifests, outputHashes, compiled,
                  stamps):
    root = _u2.Element('installed')
    root.set('buildId', buildId)
    root.set('installer', _installerVersion or '')
    for m in successfulManifests:
        e = _u2.SubElement(root, 'mod')
        e.set('name', m.modName)
        e.set('version', m.version)
        e.set('hash', m.sourceHash or '')

    for path in sorted(outputHashes or {}):
        e = _u2.SubElement(root, 'output')
        e.set('path', path)
        e.set('hash', outputHashes[path])

    for path in sorted(compiled or {}):
        stamp, modName = compiled[path]
        e = _u2.SubElement(root, 'compiled')
        e.set('path', path)
        e.set('hash', stamp)
        e.set('mod', modName)

    for path in sorted(stamps or {}):
        size, mtime = stamps[path]
        e = _u2.SubElement(root, 'stamp')
        e.set('path', path)
        e.set('size', size)
        e.set('mtime', mtime)
    data = _u2.tostring(root)
    Paths.writeBytes(Paths.installedRegistryPath(), data)

_installerVersion = None
_COMPILER_STAMP = '1'

def _finalize(_oldRegistry, successfulManifests, stats, installerVersion,
              outputHashes=None, compiled=None):
    global _installerVersion
    _installerVersion = installerVersion
    # after the commit, so the mtimes recorded are the ones on disk
    stamps = Guard.stampsFor(list((outputHashes or {}).keys())
                             + list((compiled or {}).keys()))
    try:
        _saveRegistry(Paths.gameBuildId(), successfulManifests, outputHashes,
                      compiled, stamps)
    except Exception as exc:
        logError('failed to write installed.xml: %s' % exc)
    Resources.shutdown()
    return stats

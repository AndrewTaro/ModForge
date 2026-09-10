# coding=utf-8

import time

from xml.dom import minidom as _minidom

from Codec import _u2
import Guard
import Paths
import Resources
import Validate
from Actions import applyAction, evaluateGuards
from Logger import logInfo, logError
import Planner
from Planner import (
    discoverManifests, summarizePlan, topoSort,
    validateFileReferences, validateRequirements,
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
    # Payloads commit first: reference validation and the compiler both read
    # them off disk. revertCommitted below undoes them if the registration
    # that names them never lands -- an XML registered against a SWF missing
    # its keys is a client that refuses to boot.
    payloadTx = Transaction()
    compiled, compileFailed, declared, sources = _runBuilds(eligible,
                                                            wasCompiled,
                                                            recordedStamps,
                                                            payloadTx)
    try:
        payloadTx.commit()
    except Exception as exc:
        logError('payload commit failed: %s' % exc)
        Resources.shutdown()
        return stats
    _dropOrphanedCompiles(wasCompiled, declared)

    builtChanged = compiled != wasCompiled
    # Before the early return, not after: an output clobbered by another
    # installer is exactly the case where nothing else has changed, and the
    # rebuild below is what repairs it.
    drift = Guard.detectDrift(recordedOutputs, recordedStamps)
    _reportDrift(drift)
    if not changed and not buildChanged and not builtChanged and not drift:
        logInfo('no manifest changes since last run; nothing to do')
        stats.unchanged = len(manifests)
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

    targetFiles = _collectTargetFiles(ordered)
    tx = Transaction()
    _revertOrphanedOutputs(recordedOutputs, set(targetFiles), tx)
    applied = set()
    failed = set()
    staged = []

    for relPath in targetFiles:
        try:
            updated = _applyToTarget(relPath, ordered, applied, failed,
                                     sources)
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

    successful = [m for m in ordered if m.modName not in failed]
    return _finalize(registry, successful, stats, installerVersion,
                     Guard.outputHashes(staged), compiled)

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

def _runBuilds(manifests, recorded, stamps, tx):
    import Fragment
    sources = Fragment.Sources()
    built = {}
    failedNames = set()
    declared = set()
    # absPath -> staged bytes, so a compile can read a payload generated in
    # this same run, before any of it has reached disk.
    pending = {}
    for m in manifests:
        for spec in m.builds:
            if not spec.root:
                continue
            declared.add(spec.file)
            try:
                built[spec.file] = _runOneGenerated(m, spec, sources,
                                                    recorded, stamps, tx,
                                                    pending)
            except Exception as exc:
                logError("'%s' cannot generate %s: %s"
                         % (m.modName, spec.file, exc))
                failedNames.add(m.modName)
        if m.modName in failedNames:
            for spec in m.compiles:
                declared.add(spec.out)
            continue
        for spec in m.compiles:
            declared.add(spec.out)
            try:
                built[spec.out] = _runOneCompile(m, spec, recorded, tx,
                                                 pending)
            except Exception as exc:
                logError("'%s' cannot build %s: %s"
                         % (m.modName, spec.out, exc))
                failedNames.add(m.modName)
    return built, failedNames, declared, sources

def _runOneGenerated(m, spec, sources, recorded, stamps, tx, pending):
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

def _runOneCompile(m, spec, recorded, tx, pending):
    outPath = Paths.resolveResModsTarget(spec.out)
    if outPath is None:
        raise Exception('output path escapes res_mods/: %s' % spec.out)

    sourcePaths = []
    for rel in spec.sources:
        absPath = Paths.resolveResModsTarget(rel)
        if absPath is None:
            raise Exception('source path escapes res_mods/: %s' % rel)
        if absPath not in pending and not Paths.fileExists(absPath):
            raise Exception('source not found: %s' % rel)
        sourcePaths.append(absPath)

    stamp = Paths.hashBytes(''.join(
        [_COMPILER_STAMP] + [_sourceHash(p, pending) for p in sourcePaths]))
    previous = recorded.get(spec.out)
    if (previous and previous[0] == stamp and Paths.fileExists(outPath)):
        return (stamp, m.modName)

    import UssCompile
    data, count = UssCompile.compileMarkup(sourcePaths, pending)
    tx.stage(outPath, str(data))
    logInfo("'%s' built %s from %d expression(s)"
            % (m.modName, spec.out, count))
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

def _collectTargetFiles(orderedManifests):
    seen = []
    seenSet = set()
    for m in orderedManifests:
        for t in m.builds:
            if t.root:
                continue
            if t.file not in seenSet:
                seenSet.add(t.file)
                seen.append(t.file)
    return seen

def _applyToTarget(relPath, orderedManifests, appliedOut, failedOut,
                   sources):
    pristine = Resources.loadPristine(relPath)
    if pristine is None:
        raise _TargetSkipped('cannot fetch pristine copy')

    try:
        doc = _minidom.parseString(pristine)
    except Exception as exc:
        raise _TargetSkipped('pristine is not valid XML: %s' % exc)

    mutated = False
    for m in orderedManifests:
        targets = [t for t in m.builds
                   if not t.root and t.file == relPath]
        if not targets:
            continue

        snapshot = doc.cloneNode(True)
        try:
            edited = False
            for tspec in targets:
                if not evaluateGuards(doc.documentElement, tspec.guards):
                    logInfo("'%s' guard blocks edits to %s"
                            % (m.modName, relPath))
                    continue
                for action in tspec.actions:
                    logInfo("'%s': %s on %s"
                            % (m.modName, action.kind, relPath))
                    if applyAction(doc, action, m.modName, None, sources):
                        edited = True

            if edited:
                mutated = True
                appliedOut.add(m.modName)
        except Exception as exc:
            logError("'%s' failed on %s: %s: %s"
                     % (m.modName, relPath, type(exc).__name__, exc))
            failedOut.add(m.modName)

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

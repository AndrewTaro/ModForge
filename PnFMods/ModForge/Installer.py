# coding=utf-8

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
    if not manifests:
        _dropOrphanedCompiles(wasCompiled, {})
        Validate.removeStubs()
        return _finalize(registry, [], stats, installerVersion)

    eligible = validateRequirements(manifests, installerVersion)
    compiled, compileFailed, declared, sources = _runBuilds(eligible,
                                                            wasCompiled)
    _dropOrphanedCompiles(wasCompiled, declared)

    newHashes = dict((m.modName, m.sourceHash) for m in manifests)
    oldHashes = registry.get('mods', {})
    changed = newHashes != oldHashes
    buildChanged = registry.get('buildId') != Paths.gameBuildId()
    builtChanged = compiled != wasCompiled
    if not changed and not buildChanged and not builtChanged:
        logInfo('no manifest changes since last run; nothing to do')
        stats.unchanged = len(manifests)
        return stats
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

    for relPath, why in Guard.detectDrift(registry.get('outputs', {})):
        logError("'%s' changed on disk since our last run (%s); "
                 "rebuilding it from pristine" % (relPath, why))

    targetFiles = _collectTargetFiles(ordered)
    tx = Transaction()
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

        Resources.shutdown()
        return stats

    successful = [m for m in ordered if m.modName not in failed]
    return _finalize(registry, successful, stats, installerVersion,
                     Guard.outputHashes(staged), compiled)

class _TargetSkipped(Exception):
    pass

def _runBuilds(manifests, recorded):
    import Fragment
    sources = Fragment.Sources()
    built = {}
    failedNames = set()
    declared = set()
    for m in manifests:
        for spec in m.builds:
            if not spec.root:
                continue
            declared.add(spec.file)
            try:
                built[spec.file] = _runOneGenerated(m, spec, sources)
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
                built[spec.out] = _runOneCompile(m, spec, recorded)
            except Exception as exc:
                logError("'%s' cannot build %s: %s"
                         % (m.modName, spec.out, exc))
                failedNames.add(m.modName)
    return built, failedNames, declared, sources

def _runOneGenerated(m, spec, sources):
    import Build
    outPath = Paths.resolveResModsTarget(spec.file)
    if outPath is None:
        raise Exception('output path escapes res_mods/: %s' % spec.file)
    for rel in Build.sourceFiles(spec.actions):
        if Paths.resolveResModsTarget(rel) is None:
            raise Exception('source path escapes res_mods/: %s' % rel)
    data = Build.buildDocument(spec, m.modName, sources)
    stamp = Paths.hashBytes(data)
    if Paths.hashFile(outPath) != stamp:
        Paths.writeBytes(outPath, data)
        logInfo("'%s' generated %s from %d instruction(s)"
                % (m.modName, spec.file, len(spec.actions)))
    return (stamp, m.modName)

def _runOneCompile(m, spec, recorded):
    outPath = Paths.resolveResModsTarget(spec.out)
    if outPath is None:
        raise Exception('output path escapes res_mods/: %s' % spec.out)

    sourcePaths = []
    for rel in spec.sources:
        absPath = Paths.resolveResModsTarget(rel)
        if absPath is None:
            raise Exception('source path escapes res_mods/: %s' % rel)
        if not Paths.fileExists(absPath):
            raise Exception('source not found: %s' % rel)
        sourcePaths.append(absPath)

    stamp = Paths.hashBytes(''.join(
        [_COMPILER_STAMP] + [Paths.hashFile(p) for p in sourcePaths]))
    previous = recorded.get(spec.out)
    if (previous and previous[0] == stamp and Paths.fileExists(outPath)):
        return (stamp, m.modName)

    import UssCompile
    data, count = UssCompile.compileMarkup(sourcePaths)
    Paths.writeBytes(outPath, str(data))
    logInfo("'%s' built %s from %d expression(s)"
            % (m.modName, spec.out, count))
    return (stamp, m.modName)

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
    return {
        'buildId': root.get('buildId'),
        'mods': mods,
        'outputs': outputs,
        'compiled': compiled,
    }

def _saveRegistry(buildId, successfulManifests, outputHashes, compiled):
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
    data = _u2.tostring(root)
    Paths.writeBytes(Paths.installedRegistryPath(), data)

_installerVersion = None
_COMPILER_STAMP = '1'

def _finalize(_oldRegistry, successfulManifests, stats, installerVersion,
              outputHashes=None, compiled=None):
    global _installerVersion
    _installerVersion = installerVersion
    try:
        _saveRegistry(Paths.gameBuildId(), successfulManifests, outputHashes,
                      compiled)
    except Exception as exc:
        logError('failed to write installed.xml: %s' % exc)
    Resources.shutdown()
    return stats

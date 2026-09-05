# coding=utf-8

import Manifest as manifestMod
import Paths
import Resources
from Logger import logError, logInfo
from Codec import _u1

class PlannerError(Exception):
    pass

def discoverManifests():
    found = {}
    seenPaths = []

    blueprintsRoot = Paths.blueprintsDir()
    for name in Paths.listFiles(blueprintsRoot, suffix='.xml'):
        absPath = blueprintsRoot + name
        m = _readManifestFile(absPath)
        if m is None:
            continue
        if m.modName in found:
            logInfo("duplicate mod name '%s' (already from %s); ignoring %s"
                    % (m.modName, found[m.modName].sourcePath, absPath))
            continue
        found[m.modName] = m
        seenPaths.append(absPath)

    pnf = Paths.pnfModsDir()
    for sub in Paths.listSubdirs(pnf):
        candidate = pnf + sub + '/manifest.xml'
        if not Paths.fileExists(candidate):
            continue
        m = _readManifestFile(candidate)
        if m is None:
            continue
        if m.modName in found:
            logInfo("mod '%s' already discovered at %s; ignoring fallback %s"
                    % (m.modName, found[m.modName].sourcePath, candidate))
            continue
        found[m.modName] = m
        seenPaths.append(candidate)

    logInfo('discovered %d manifest(s) at %d location(s)'
            % (len(found), len(seenPaths)))
    return list(found.values())

def _readManifestFile(absPath):
    try:
        data = Paths.readBytes(absPath)
    except Exception as exc:
        logError('cannot read manifest %s: %s' % (absPath, exc))
        return None
    try:
        m = manifestMod.parseManifest(absPath, data)
    except manifestMod.ManifestError as exc:
        logError('invalid manifest %s: %s' % (absPath, exc))
        return None
    m.sourceHash = Paths.hashBytes(data)
    return m

def validateRequirements(manifests, installerVersion):
    byName = dict((m.modName, m) for m in manifests)
    accepted = []
    for m in manifests:
        if not _checkInstallerRequirement(m, installerVersion):
            continue
        if not _checkModRequirements(m, byName):
            continue
        accepted.append(m)
    return accepted

def _checkInstallerRequirement(m, installerVersion):
    req = m.installerRequirement
    if not req:
        return True
    if not manifestMod.satisfiesConstraint(installerVersion, req):
        logError(
            "'%s' requires installer %s but ModForge is %s; skipping"
            % (m.modName, req, installerVersion))
        return False
    return True

def _checkModRequirements(m, byName):
    for depName, constraint in m.modRequirements:
        dep = byName.get(depName)
        if dep is None:
            logError(
                "'%s' requires mod '%s' which is not installed; skipping"
                % (m.modName, depName))
            return False
        if constraint and not manifestMod.satisfiesConstraint(dep.version,
                                                              constraint):
            logError(
                "'%s' requires %s %s but %s %s is installed; skipping"
                % (m.modName, depName, constraint, depName, dep.version))
            return False
    return True

def validateFileReferences(m):
    missing = []
    for t in m.targets:
        for action in t.actions:
            if action.kind not in ('insert', 'replace'):
                continue
            for elem in action.payload:
                _collectReferencedFiles(elem, missing)
    if not missing:
        return True
    for ref in missing:
        logError("'%s' references missing file: %s" % (m.modName, ref))
    logError("skipping '%s' due to %d missing file reference(s)"
             % (m.modName, len(missing)))
    return False

_FILE_REF_TAGS = ('swffile', 'xmlfile')

def _collectReferencedFiles(etElem, missingOut):
    tag = etElem.tag
    if tag in _FILE_REF_TAGS:
        candidate = (etElem.text or '').strip() or etElem.get('path')
        if candidate:
            if not _fileReferenceExists(candidate):
                missingOut.append(candidate)
    for child in etElem:
        _collectReferencedFiles(child, missingOut)

def _fileReferenceExists(candidate):
    return resolveReference(candidate) is not None

def resolveReference(candidate):
    for relPath in _candidateRelPaths(candidate):
        if Paths.fileExists(Paths.resModsDir() + relPath):
            return relPath
        if Resources.pristineExists(relPath):
            return relPath
    return None

_REF_BASE_DIRS = ('gui/unbound/', 'gui/flash/')

def _candidateRelPaths(candidate):
    base = Paths.resModsDir()
    out = []
    for prefix in _REF_BASE_DIRS + ('',):
        absPath = _u1.path.abspath(base + prefix + candidate)
        absPath = absPath.replace('\\', '/')
        if not absPath.startswith(base):
            continue
        relPath = absPath[len(base):]
        if relPath and relPath not in out:
            out.append(relPath)
    return out

def topoSort(manifests):
    byName = dict((m.modName, m) for m in manifests)

    inDegree = dict((m.modName, 0) for m in manifests)
    dependents = dict((m.modName, []) for m in manifests)
    for m in manifests:
        for depName, _ in m.modRequirements:
            if depName in byName:
                inDegree[m.modName] += 1
                dependents[depName].append(m.modName)

    ready = [m for m in manifests if inDegree[m.modName] == 0]
    ready.sort(key=_orderKey)
    out = []
    while ready:
        nxt = ready.pop(0)
        out.append(nxt)
        for childName in dependents[nxt.modName]:
            inDegree[childName] -= 1
            if inDegree[childName] == 0:
                ready.append(byName[childName])
        ready.sort(key=_orderKey)

    if len(out) != len(manifests):
        unresolved = [m.modName for m in manifests
                      if m.modName not in set(x.modName for x in out)]
        logError('dependency cycle involves: %s; these mods will be skipped'
                 % ', '.join(unresolved))
    return out

def _orderKey(m):
    base = m.sourcePath.rsplit('/', 1)[-1]
    return (-m.priority, base)

def summarizePlan(orderedManifests):
    if not orderedManifests:
        logInfo('no eligible mods to apply')
        return
    logInfo('install order:')
    for idx, m in enumerate(orderedManifests, start=1):
        logInfo('  %d. %s %s (priority %d)'
                % (idx, m.modName, m.version, m.priority))

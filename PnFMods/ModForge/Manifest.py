# coding=utf-8

import re

from Logger import logInfo
from Codec import _u2

class Manifest(object):
    __slots__ = (
        'modName', 'version', 'priority',
        'installerRequirement',
        'modRequirements',
        'targets',
        'sourcePath',
        'sourceHash',
    )

    def __init__(self):
        self.modName = None
        self.version = None
        self.priority = 0
        self.installerRequirement = None
        self.modRequirements = []
        self.targets = []
        self.sourcePath = None
        self.sourceHash = None

class TargetSpec(object):
    __slots__ = ('file', 'guards', 'actions')

    def __init__(self):
        self.file = None
        self.guards = []
        self.actions = []

class Guard(object):
    __slots__ = ('kind', 'expr')

    def __init__(self, kind, expr):
        self.kind = kind
        self.expr = expr

class ActionSpec(object):
    __slots__ = (
        'kind',
        'select',
        'into',
        'before',
        'after',
        'payload',
        'attribute',
        'fromValue',
        'toValue',
        'overrides',
    )

    def __init__(self, kind):
        self.kind = kind
        self.select = None
        self.into = None
        self.before = None
        self.after = None
        self.payload = []
        self.attribute = None
        self.fromValue = None
        self.toValue = None
        self.overrides = []

class ManifestError(Exception):
    pass

_KNOWN_MOD_ATTRS = set(['name', 'version', 'priority'])
_KNOWN_TARGET_ATTRS = set(['file'])
_KNOWN_INSERT_ATTRS = set(['into', 'before', 'after'])
_KNOWN_REMOVE_ATTRS = set(['select'])
_KNOWN_REPLACE_ATTRS = set(['select'])
_KNOWN_RENAME_ATTRS = set(['select', 'attribute', 'from', 'to'])
_KNOWN_COPY_ATTRS = set(['select', 'into', 'before', 'after'])
_KNOWN_GUARD_ATTRS = set(['ifExists', 'ifNotExists'])

def parseManifest(filePath, fileBytes):
    try:
        root = _u2.fromstring(fileBytes)
    except Exception as exc:
        raise ManifestError('not valid XML: %s' % exc)
    if root.tag != 'mod':
        raise ManifestError("root element must be <mod>, got <%s>" % root.tag)

    m = Manifest()
    m.sourcePath = filePath

    _warnUnknown(root, _KNOWN_MOD_ATTRS,
                 'mod attribute', filePath)

    m.modName = root.get('name')
    m.version = root.get('version')
    if not m.modName:
        raise ManifestError('<mod> requires a `name` attribute')
    if not m.version:
        raise ManifestError("<mod name='%s'> requires a `version` attribute"
                            % m.modName)
    try:
        m.priority = int(root.get('priority', '0'))
    except Exception:
        logInfo('%s: priority must be an integer, got %r; using 0'
                % (m.modName, root.get('priority')))
        m.priority = 0

    for child in root:
        if child.tag == 'requires':
            _parseRequires(m, child)
        elif child.tag == 'target':
            m.targets.append(_parseTarget(m, child))
        else:
            logInfo('%s: ignoring unknown element <%s>' % (m.modName, child.tag))

    if not m.targets:
        logInfo('%s: manifest has no <target> blocks' % m.modName)

    return m

def _parseRequires(m, node):
    inst = node.get('installer')
    if inst is not None:
        m.installerRequirement = inst.strip()
        return
    depMod = node.get('mod')
    if depMod is None:
        logInfo('%s: <requires> needs `installer` or `mod` attribute'
                % m.modName)
        return
    constraint = node.get('version')
    m.modRequirements.append((depMod.strip(),
                              constraint.strip() if constraint else None))

def _parseTarget(m, node):
    t = TargetSpec()
    _warnUnknown(node, _KNOWN_TARGET_ATTRS,
                 'target attribute', m.modName)
    t.file = node.get('file')
    if not t.file:
        raise ManifestError("%s: <target> requires `file` attribute" % m.modName)
    for child in node:
        if child.tag == 'guard':
            t.guards.append(_parseGuard(m, child))
        elif child.tag == 'insert':
            t.actions.append(_parseInsert(m, child))
        elif child.tag == 'remove':
            t.actions.append(_parseRemove(m, child))
        elif child.tag == 'replace':
            t.actions.append(_parseReplace(m, child))
        elif child.tag == 'rename':
            t.actions.append(_parseRename(m, child))
        elif child.tag == 'copy':
            t.actions.append(_parseCopy(m, child))
        else:
            logInfo("%s: ignoring unknown child <%s> inside <target file='%s'>"
                    % (m.modName, child.tag, t.file))
    return t

def _parseGuard(m, node):
    _warnUnknown(node, _KNOWN_GUARD_ATTRS, 'guard attribute', m.modName)
    expr = node.get('ifExists')
    if expr is not None:
        return Guard('ifExists', expr)
    expr = node.get('ifNotExists')
    if expr is not None:
        return Guard('ifNotExists', expr)
    raise ManifestError(
        '%s: <guard> requires either ifExists or ifNotExists' % m.modName)

def _parseInsert(m, node):
    _warnUnknown(node, _KNOWN_INSERT_ATTRS, 'insert attribute', m.modName)
    a = ActionSpec('insert')
    a.into = node.get('into')
    a.before = node.get('before')
    a.after = node.get('after')
    if not a.into and not a.before and not a.after:
        raise ManifestError('%s: <insert> needs into=, before=, or after='
                            % m.modName)
    a.payload = list(node)
    if not a.payload:
        logInfo('%s: <insert> has no payload elements; will be a no-op'
                % m.modName)
    return a

def _parseRemove(m, node):
    _warnUnknown(node, _KNOWN_REMOVE_ATTRS, 'remove attribute', m.modName)
    a = ActionSpec('remove')
    a.select = node.get('select')
    if not a.select:
        raise ManifestError('%s: <remove> needs `select`' % m.modName)
    return a

def _parseReplace(m, node):
    _warnUnknown(node, _KNOWN_REPLACE_ATTRS, 'replace attribute', m.modName)
    a = ActionSpec('replace')
    a.select = node.get('select')
    if not a.select:
        raise ManifestError('%s: <replace> needs `select`' % m.modName)
    a.payload = list(node)
    return a

def _parseRename(m, node):
    _warnUnknown(node, _KNOWN_RENAME_ATTRS, 'rename attribute', m.modName)
    a = ActionSpec('rename')
    a.select = node.get('select')
    a.attribute = node.get('attribute')
    a.fromValue = node.get('from')
    a.toValue = node.get('to')
    if not (a.select and a.attribute and a.toValue is not None):
        raise ManifestError(
            '%s: <rename> needs `select`, `attribute`, and `to`' % m.modName)
    return a

def _parseCopy(m, node):
    _warnUnknown(node, _KNOWN_COPY_ATTRS, 'copy attribute', m.modName)
    a = ActionSpec('copy')
    a.select = node.get('select')
    a.into = node.get('into')
    a.before = node.get('before')
    a.after = node.get('after')
    if not a.select:
        raise ManifestError('%s: <copy> needs `select`' % m.modName)
    if not a.into and not a.before and not a.after:
        raise ManifestError(
            '%s: <copy> needs into=, before=, or after=' % m.modName)
    for child in node:
        if child.tag == 'override':
            attr = child.get('attribute')
            value = child.get('value', '')
            if not attr:
                logInfo("%s: <override> missing `attribute`; ignored" % m.modName)
                continue
            a.overrides.append((attr, value))
        else:
            logInfo('%s: ignoring unknown <copy> child <%s>'
                    % (m.modName, child.tag))
    return a

def _warnUnknown(node, knownAttrs, label, context):
    for key in node.keys():
        if key not in knownAttrs:
            logInfo('%s: unknown %s `%s`' % (context, label, key))

_VERSION_RE = re.compile(r'^(\d+(?:\.\d+)*)')
_CONSTRAINT_RE = re.compile(r'^(>=|<=|==|>|<)?\s*(\d+(?:\.\d+)*)\s*$')

def parseVersion(text):
    if not text:
        return None
    m = _VERSION_RE.match(text.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split('.'))

def _alignedPair(a, b):
    width = max(len(a), len(b))
    return (a + (0,) * (width - len(a)), b + (0,) * (width - len(b)))

def satisfiesConstraint(versionText, constraint):
    if constraint is None or not constraint.strip():
        return True
    m = _CONSTRAINT_RE.match(constraint.strip())
    if not m:
        return False
    op = m.group(1) or '>='
    required = parseVersion(m.group(2))
    actual = parseVersion(versionText)
    if required is None or actual is None:
        return False
    actual, required = _alignedPair(actual, required)
    if op == '>=':
        return actual >= required
    if op == '<=':
        return actual <= required
    if op == '==':
        return actual == required
    if op == '>':
        return actual > required
    if op == '<':
        return actual < required
    return False

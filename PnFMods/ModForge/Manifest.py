# coding=utf-8

import re

from Logger import logInfo
from Codec import _u2

VANILLA_MARKUP = 'gui/unbound/markup.xml'
VANILLA_STYLES = 'gui/unbound/styles.xml'
USS_SETTINGS = 'gui/uss_settings.xml'
BATTLE_ELEMENTS = 'gui/battle_elements.xml'
PAYLOAD_DIR = 'gui/unbound/mods/'
USS_PAYLOAD_DIR = '../unbound/mods/'
UNBOUND_ELEMENT_CLASS = 'lesta.libs.unbound.UnboundElement'
UNBOUND_CONTROLLER_CLASS = ('lesta.dialogs.battle_window_controllers'
                            '.UnboundElementController')

class Manifest(object):
    __slots__ = (
        'modName', 'version', 'priority',
        'installerRequirement',
        'modRequirements',
        'builds',
        'compiles',
        'sourcePath',
        'sourceHash',
    )

    def __init__(self):
        self.modName = None
        self.version = None
        self.priority = 0
        self.installerRequirement = None
        self.modRequirements = []
        self.builds = []
        self.compiles = []
        self.sourcePath = None
        self.sourceHash = None

class BuildSpec(object):
    __slots__ = ('file', 'root', 'guards', 'actions')

    def __init__(self):
        self.file = None
        self.root = None
        self.guards = []
        self.actions = []

class CompileSpec(object):
    __slots__ = ('out', 'sources')

    def __init__(self):
        self.out = None
        self.sources = []

class Guard(object):
    __slots__ = ('kind', 'expr')

    def __init__(self, kind, expr):
        self.kind = kind
        self.expr = expr

class ActionSpec(object):
    __slots__ = (
        'kind',
        'select',
        'source',
        'into',
        'before',
        'after',
        'payload',
        'attribute',
        'fromValue',
        'toValue',
        'actions',
    )

    def __init__(self, kind):
        self.kind = kind
        self.select = None
        self.source = None
        self.into = None
        self.before = None
        self.after = None
        self.payload = []
        self.attribute = None
        self.fromValue = None
        self.toValue = None
        self.actions = []

class ManifestError(Exception):
    pass

_KNOWN_MOD_ATTRS = set(['name', 'version', 'priority'])
_KNOWN_BUILD_ATTRS = set(['file', 'root'])
_KNOWN_INSERT_ATTRS = set(['into', 'before', 'after'])
_KNOWN_REMOVE_ATTRS = set(['select'])
_KNOWN_REPLACE_ATTRS = set(['select'])
_KNOWN_SET_ATTRIBUTE_ATTRS = set(['select', 'attribute', 'from', 'to'])
_KNOWN_COPY_ATTRS = set(['select', 'from', 'into', 'before', 'after'])
_KNOWN_GUARD_ATTRS = set(['ifExists', 'ifNotExists'])
_KNOWN_COMPILE_ATTRS = set(['out', 'source'])
_KNOWN_SOURCE_ATTRS = set(['file'])
_KNOWN_UB_BUILD_ATTRS = set(['name', 'autoCompile'])
_KNOWN_UB_REGISTER_ATTRS = set(['name', 'swf'])
_KNOWN_UB_MOUNT_ATTRS = set(['rootElementId', 'name', 'hitTest', 'url'])

def parseManifest(filePath, fileBytes):
    try:
        root = _u2.fromstring(fileBytes)
    except Exception as exc:
        raise ManifestError('not valid XML: %s' % exc)
    if root.tag != 'mod':
        raise ManifestError("root element must be <mod>, got <%s>" % root.tag)

    m = Manifest()
    m.sourcePath = filePath

    _warnUnknown(root, _KNOWN_MOD_ATTRS, 'mod attribute', filePath)

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
        elif child.tag == 'build':
            m.builds.append(_parseBuild(m, child))
        elif child.tag == 'ubBuild':
            m.builds.extend(_parseUbBuild(m, child))
        elif child.tag == 'ubCompile':
            m.compiles.append(_parseCompile(m, child))
        elif child.tag == 'ubRegister':
            m.builds.append(_parseUbRegister(m, child))
        elif child.tag == 'ubMountInBattle':
            m.builds.append(_parseUbMountInBattle(m, child))
        else:
            logInfo('%s: ignoring unknown element <%s>' % (m.modName, child.tag))

    if not m.builds and not m.compiles:
        logInfo('%s: manifest has nothing to build' % m.modName)

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

def _parseBuild(m, node):
    _warnUnknown(node, _KNOWN_BUILD_ATTRS, 'build attribute', m.modName)
    b = BuildSpec()
    b.file = node.get('file')
    if not b.file:
        raise ManifestError("%s: <build> requires `file`" % m.modName)
    root = node.get('root')
    b.root = root.strip() if root else None
    if b.root is not None and not _TAG_RE.match(b.root):
        raise ManifestError("%s: <build root='%s'> is not a usable element name"
                            % (m.modName, b.root))
    for child in node:
        if child.tag == 'guard':
            if b.root:
                raise ManifestError(
                    "%s: <build file='%s' root='%s'> cannot carry a <guard>; "
                    "it starts from an empty document" % (m.modName, b.file,
                                                          b.root))
            b.guards.append(_parseGuard(m, child))
        else:
            action = _parseAction(m, child, "<build file='%s'>" % b.file)
            if action is not None:
                b.actions.append(action)
    return b

def _parseAction(m, node, context):
    parser = _ACTION_PARSERS.get(node.tag)
    if parser is None:
        logInfo('%s: ignoring unknown child <%s> inside %s'
                % (m.modName, node.tag, context))
        return None
    return parser(m, node)

def _parseNested(m, node, context):
    out = []
    for child in node:
        action = _parseAction(m, child, context)
        if action is not None:
            out.append(action)
    return out

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

def _parseSetAttribute(m, node):
    _warnUnknown(node, _KNOWN_SET_ATTRIBUTE_ATTRS, 'setAttribute attribute',
                 m.modName)
    a = ActionSpec('setAttribute')
    a.select = node.get('select')
    a.attribute = node.get('attribute')
    a.fromValue = node.get('from')
    a.toValue = node.get('to')
    if not a.attribute or a.toValue is None:
        raise ManifestError(
            '%s: <setAttribute> needs `attribute` and `to`' % m.modName)
    return a

def _parseCopy(m, node):
    _warnUnknown(node, _KNOWN_COPY_ATTRS, 'copy attribute', m.modName)
    a = ActionSpec('copy')
    a.select = node.get('select')
    source = node.get('from')
    a.source = source.strip() if source else None
    a.into = node.get('into')
    a.before = node.get('before')
    a.after = node.get('after')
    if not a.select:
        raise ManifestError('%s: <copy> needs `select`' % m.modName)
    if not a.into and not a.before and not a.after:
        raise ManifestError(
            '%s: <copy> needs into=, before=, or after=' % m.modName)
    a.actions = _parseNested(m, node, "<copy select='%s'>" % a.select)
    return a

_ACTION_PARSERS = {
    'insert': _parseInsert,
    'remove': _parseRemove,
    'replace': _parseReplace,
    'setAttribute': _parseSetAttribute,
    'copy': _parseCopy,
}

def _parseCompile(m, node):
    _warnUnknown(node, _KNOWN_COMPILE_ATTRS, 'ubCompile attribute', m.modName)
    c = CompileSpec()
    c.out = node.get('out')
    if not c.out:
        raise ManifestError("%s: <ubCompile> requires `out`" % m.modName)
    source = node.get('source')
    if source:
        c.sources.append(source.strip())
    for child in node:
        if child.tag == 'source':
            _warnUnknown(child, _KNOWN_SOURCE_ATTRS, 'source attribute',
                         m.modName)
            f = child.get('file')
            if not f:
                raise ManifestError("%s: <source> requires `file`" % m.modName)
            c.sources.append(f.strip())
        else:
            logInfo('%s: ignoring unknown <ubCompile> child <%s>'
                    % (m.modName, child.tag))
    if not c.sources:
        raise ManifestError("%s: <ubCompile out='%s'> has no source"
                            % (m.modName, c.out))
    return c

def _parseUbBuild(m, node):
    _warnUnknown(node, _KNOWN_UB_BUILD_ATTRS, 'ubBuild attribute', m.modName)
    name = _payloadName(m, node, 'ubBuild')
    autoCompile = _boolAttr(node.get('autoCompile'), True)

    b = BuildSpec()
    b.file = PAYLOAD_DIR + name + '.xml'
    b.root = 'ui'
    b.actions = _parseNested(m, node, "<ubBuild name='%s'>" % name)
    if not b.actions:
        raise ManifestError("%s: <ubBuild name='%s'> has nothing to assemble"
                            % (m.modName, name))

    if autoCompile:
        c = CompileSpec()
        c.out = PAYLOAD_DIR + name + '.swf'
        c.sources.append(b.file)
        m.compiles.append(c)

    return [b, _ussRegistration(name, autoCompile)]

def _parseUbRegister(m, node):
    _warnUnknown(node, _KNOWN_UB_REGISTER_ATTRS, 'ubRegister attribute',
                 m.modName)
    name = _payloadName(m, node, 'ubRegister')
    return _ussRegistration(name, _boolAttr(node.get('swf'), True))

def _ussRegistration(name, withSwf):
    payload = [_textElement('xmlfile', USS_PAYLOAD_DIR + name + '.xml')]
    if withSwf:
        payload.append(_textElement('swffile', USS_PAYLOAD_DIR + name + '.swf'))
    a = ActionSpec('insert')
    a.into = 'mods'
    a.payload = payload
    b = BuildSpec()
    b.file = USS_SETTINGS
    b.actions.append(a)
    return b

def _parseUbMountInBattle(m, node):
    _warnUnknown(node, _KNOWN_UB_MOUNT_ATTRS, 'ubMountInBattle attribute',
                 m.modName)
    rootElementId = node.get('rootElementId')
    if not rootElementId:
        raise ManifestError('%s: <ubMountInBattle> requires `rootElementId`'
                            % m.modName)
    rootElementId = rootElementId.strip()
    name = (node.get('name') or rootElementId).strip()
    if not name:
        raise ManifestError('%s: <ubMountInBattle> has an empty `name`'
                            % m.modName)

    element = _u2.Element('element')
    element.set('name', name)
    element.set('class', UNBOUND_ELEMENT_CLASS)
    url = node.get('url')
    if url:
        element.set('url', url.strip())
    props = _u2.SubElement(element, 'properties')
    props.set('rootElementId', rootElementId)
    props.set('hitTest', 'true' if _boolAttr(node.get('hitTest'), True)
              else 'false')

    controller = _u2.Element('controller')
    controller.set('class', UNBOUND_CONTROLLER_CLASS)
    controller.set('clips', name)

    b = BuildSpec()
    b.file = BATTLE_ELEMENTS
    b.actions.append(_insertInto('elementList', element))
    b.actions.append(_insertInto('controllers', controller))
    return b

def _insertInto(container, payloadElement):
    a = ActionSpec('insert')
    a.into = container
    a.payload = [payloadElement]
    return a

def _textElement(tag, text):
    el = _u2.Element(tag)
    el.text = text
    return el

_TAG_RE = re.compile(r'^[A-Za-z_][\w.-]*$')
_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')

def _payloadName(m, node, label):
    name = node.get('name')
    if not name:
        raise ManifestError('%s: <%s> requires `name`' % (m.modName, label))
    name = name.strip()
    if not _NAME_RE.match(name):
        raise ManifestError("%s: <%s name='%s'> may only use letters, digits, "
                            "dot, dash and underscore" % (m.modName, label,
                                                          name))
    return name

def _boolAttr(value, default):
    if value is None:
        return default
    return value.strip().lower() not in ('false', '0', 'no', 'off')

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

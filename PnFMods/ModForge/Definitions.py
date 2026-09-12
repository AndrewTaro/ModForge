# coding=utf-8

from xml.dom import minidom as _minidom

import Build
import BlockSlice
import Manifest
import Paths
from Actions import applyAction
from Logger import logError

class DefinitionError(Exception):
    pass

# (vanilla source, wrapper tag, key attribute) -- the whole difference between
# the two namespaces. Everything below is one implementation over this triple.
NAMESPACES = {
    'block': (Manifest.VANILLA_MARKUP, 'block', 'className'),
    'css': (Manifest.VANILLA_STYLES, 'css', 'name'),
}

_MISSING = object()

def collect(orderedManifests):
    """[((namespace, name), [(manifest, spec), ...]), ...]

    Contributions keep the install order they were given; keys keep first
    appearance, so the emitted set does not depend on dict hash order."""
    groups = {}
    order = []
    for m in orderedManifests:
        for spec in m.definitions:
            key = (spec.namespace, spec.name)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((m, spec))
    return [(key, groups[key]) for key in order]

def label(namespace, name):
    return "<%s name='%s'>" % (Manifest.DEFINITION_VERBS[namespace], name)

class Merger(object):
    """Assembles one document per definition out of vanilla plus every mod
    that names it."""

    def __init__(self, sources):
        self.sources = sources
        self._allNames = {}

    def build(self, key, contributions, appliedOut=None, failedOut=None):
        """(bytes, isNew), the bytes None when no contributor changed anything.

        A contributor that raises is rolled back to the document as it stood
        before it and reported; its peers still land."""
        namespace, name = key
        doc, isNew = self.baseline(namespace, name)
        applied = []
        try:
            for m, spec in contributions:
                snapshot = doc.cloneNode(True)
                try:
                    _checkSources(spec.actions)
                    changed = 0
                    for action in spec.actions:
                        changed += applyAction(doc, action, m.modName,
                                               _element(doc, namespace, name),
                                               self.sources) or 0
                    _checkShape(doc, namespace, name)
                except Exception as exc:
                    logError("'%s' failed on %s: %s: %s"
                             % (m.modName, label(namespace, name),
                                type(exc).__name__, exc))
                    if failedOut is not None:
                        failedOut.add(m.modName)
                    doc.unlink()
                    doc = snapshot
                    continue
                snapshot.unlink()
                if changed:
                    applied.append(m.modName)
                    if appliedOut is not None:
                        appliedOut.add(m.modName)
            if not applied:
                return None, isNew
            return Build.serialize(doc), isNew
        finally:
            doc.unlink()

    def baseline(self, namespace, name):
        """(document, isNew), the definition element its only child."""
        relPath, tag, attr = NAMESPACES[namespace]
        span = self.sources.index(relPath, tag, attr).get(name, _MISSING)
        if span is None:
            raise DefinitionError(
                "%s is defined more than once at the top level of %s; which "
                "one to build on is ambiguous" % (label(namespace, name),
                                                  relPath))
        if span is _MISSING:
            if self._definedNested(relPath, tag, attr, name):
                # Not a drift report: the name IS in this build, just not as a
                # definition of its own, so there is nothing to slice.
                logError('%s names a <%s> that vanilla only ever writes inside '
                         'another one; building it from empty'
                         % (label(namespace, name), tag))
            return _emptyDoc(tag, attr, name), True

        # Sliced outside the try: this handler speaks about parsing, and a
        # bad span reported as a parse failure is a lie about the cause.
        fragment = self.sources.raw(relPath)[span[0]:span[1]]
        try:
            fragment = _minidom.parseString(fragment)
        except Exception as exc:
            raise DefinitionError('%s does not parse out of %s: %s'
                                  % (label(namespace, name), relPath, exc))
        doc = _minidom.parseString('<ui/>')
        doc.documentElement.appendChild(
            doc.importNode(fragment.documentElement, True))
        fragment.unlink()
        return doc, False

    def _definedNested(self, relPath, tag, attr, name):
        key = (relPath, tag, attr)
        names = self._allNames.get(key)
        if names is None:
            names = set(BlockSlice.class_names(self.sources.raw(relPath),
                                               tag, attr))
            self._allNames[key] = names
        return name in names

def _checkSources(actions):
    for rel in Build.sourceFiles(actions):
        if Paths.resolveResModsTarget(rel) is None:
            raise DefinitionError('copy source escapes res_mods/: %s' % rel)

def _emptyDoc(tag, attr, name):
    doc = _minidom.parseString('<ui/>')
    el = doc.createElement(tag)
    el.setAttribute(attr, name)
    doc.documentElement.appendChild(el)
    return doc

def _element(doc, namespace, name):
    """The definition itself, so a selector is written against it and not
    against the `<ui>` wrapper Forge puts around it."""
    for child in doc.documentElement.childNodes:
        if child.nodeType == child.ELEMENT_NODE:
            return child
    raise DefinitionError('%s was removed from its own document'
                          % label(namespace, name))

def _checkShape(doc, namespace, name):
    """One file holds exactly the one definition it is named for.

    The `..` axis reaches the <ui> wrapper, so a mod could otherwise write a
    sibling here -- a name outside Forge's index, in a file Forge registers.
    That is the cross-file collision the per-class shape exists to remove."""
    _, tag, attr = NAMESPACES[namespace]
    kids = [c for c in doc.documentElement.childNodes
            if c.nodeType == c.ELEMENT_NODE]
    if len(kids) != 1:
        raise DefinitionError('%s would emit %d top-level <%s>; a definition '
                              'file holds exactly one'
                              % (label(namespace, name), len(kids), tag))
    el = kids[0]
    if el.tagName != tag or el.getAttribute(attr) != name:
        raise DefinitionError("%s would emit <%s %s='%s'> instead"
                              % (label(namespace, name), el.tagName, attr,
                                 el.getAttribute(attr)))

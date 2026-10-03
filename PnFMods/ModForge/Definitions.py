# coding=utf-8

import re

from xml.dom import minidom as _minidom

import Build
import BlockSlice
import Manifest
from Actions import CLAIM_PREFIX, applyAction, stripClaims
from Logger import logError, logInfo

class DefinitionError(Exception):
    pass



NAMESPACES = {
    'block': (Manifest.VANILLA_MARKUP, 'block', 'className'),
    'css': (Manifest.VANILLA_STYLES, 'css', 'name'),
}

_MISSING = object()

def collect(orderedManifests):




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

_NAME_RE = re.compile(r'^[A-Za-z_][\w.\-]*$')

class Claims(object):









    def __init__(self):
        self.refused = []

    def claim(self, node, attr, modName):
        if not _NAME_RE.match(attr or ''):


            return True
        key = CLAIM_PREFIX + attr
        held = node.getAttribute(key) if node.hasAttribute(key) else None
        if held is not None and held != modName:
            self.refused.append((modName, held, node.tagName, attr))
            return False
        node.setAttribute(key, modName)
        return True

def reportRefused(refused, where):
    for modName, held, tagName, attr in refused:
        logError("'%s' cannot set %s on <%s> in %s: '%s' set it first and "
                 "has the higher priority"
                 % (modName, attr, tagName, where, held))

class Merger(object):



    def __init__(self, sources, quiet=False):
        self.sources = sources
        self.refused = []
        self._allNames = {}

        self.quiet = quiet

    def build(self, key, contributions, appliedOut=None, failedOut=None):




        namespace, name = key
        doc, isNew = self.baseline(namespace, name)
        pristine = doc.cloneNode(True)
        claims = Claims()
        applied = []
        try:
            for m, spec in contributions:
                snapshot = doc.cloneNode(True)
                refusedMark = len(claims.refused)
                try:
                    changed = self._contribute(doc, snapshot, pristine, m,
                                               spec, key, claims)
                    _checkShape(doc, namespace, name)
                except Exception as exc:
                    if not self.quiet:
                        logError("'%s' failed on %s: %s: %s"
                                 % (m.modName, label(namespace, name),
                                    type(exc).__name__, exc))
                    if failedOut is not None:
                        failedOut.add(m.modName)
                    doc.unlink()
                    doc = snapshot




                    del claims.refused[refusedMark:]
                    continue
                snapshot.unlink()
                if changed:
                    applied.append(m.modName)
                    if appliedOut is not None:
                        appliedOut.add(m.modName)
            self._reportRefused(claims, key)
            self.refused.extend(claims.refused)
            if not applied:
                return None, isNew
            stripClaims(doc.documentElement)
            return Build.serialize(doc), isNew
        finally:
            pristine.unlink()
            doc.unlink()

    def _contribute(self, doc, snapshot, pristine, m, spec, key, claims):
        namespace, name = key
        changed = 0
        for action in spec.actions:
            try:
                changed += applyAction(doc, action, m.modName,
                                       _element(doc, namespace, name),
                                       self.sources, claims) or 0
            except Exception as exc:
                blame = self._blame(action, snapshot, pristine, key)
                if blame == 'self':
                    raise type(exc)('%s (an earlier action of this mod changed '
                                    'what it names)' % exc)
                if blame != 'peer':
                    raise
                if not self.quiet:
                    logInfo("'%s': %s on %s skipped -- a mod applied before it "
                            "changed what that names (%s)"
                            % (m.modName, action.kind, label(namespace, name),
                               exc))
        return changed

    def _blame(self, action, snapshot, pristine, key):







        if self._replays(action, snapshot, key):
            return 'self'
        if self._replays(action, pristine, key):
            return 'peer'
        return 'author'

    def _replays(self, action, doc, key):
        namespace, name = key
        trial = doc.cloneNode(True)
        try:
            applyAction(trial, action, '', _element(trial, namespace, name),
                        self.sources)
            return True
        except Exception:
            return False
        finally:
            trial.unlink()

    def _reportRefused(self, claims, key):
        if not self.quiet:
            reportRefused(claims.refused, label(*key))

    def baseline(self, namespace, name):

        relPath, tag, attr = NAMESPACES[namespace]
        span = self.sources.index(relPath, tag, attr).get(name, _MISSING)
        if span is None:
            raise DefinitionError(
                "%s is defined more than once at the top level of %s; which "
                "one to build on is ambiguous" % (label(namespace, name),
                                                  relPath))
        if span is _MISSING:
            if not self.quiet and self._definedNested(relPath, tag, attr,
                                                      name):


                logError('%s names a <%s> that vanilla only ever writes inside '
                         'another one; building it from empty'
                         % (label(namespace, name), tag))
            return _emptyDoc(tag, attr, name), True



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

def _emptyDoc(tag, attr, name):
    doc = _minidom.parseString('<ui/>')
    el = doc.createElement(tag)
    el.setAttribute(attr, name)
    doc.documentElement.appendChild(el)
    return doc

def _element(doc, namespace, name):


    for child in doc.documentElement.childNodes:
        if child.nodeType == child.ELEMENT_NODE:
            return child
    raise DefinitionError('%s was removed from its own document'
                          % label(namespace, name))

def _checkShape(doc, namespace, name):





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

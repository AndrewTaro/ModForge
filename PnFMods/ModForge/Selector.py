# coding=utf-8

import re

_STEP_RE = re.compile(r'([A-Za-z_*][\w.-]*)((?:\[[^\]]*\])*)')
_PRED_RE = re.compile(r'\[([^\]]*)\]')

_ATTR_PRED_RE = re.compile(r"""^@([\w.-]+)\s*=\s*(?:'([^']*)'|"([^"]*)")$""")
_TEXT_PRED_RE = re.compile(r"""^text\(\)\s*=\s*(?:'([^']*)'|"([^"]*)")$""")
_POS_PRED_RE = re.compile(r'^(\d+|last\(\))$')

class SelectorError(Exception):
    pass

class _Predicate(object):
    __slots__ = ('kind', 'name', 'value')

    def __init__(self, kind, name, value):
        self.kind = kind
        self.name = name
        self.value = value

    def matches(self, node, indexAmongSiblings, totalSiblings):
        if self.kind == 'attr':
            if node.hasAttribute(self.name):
                return node.getAttribute(self.name) == self.value
            return False
        if self.kind == 'text':
            text = _innerText(node)
            return text == self.value
        if self.kind == 'pos':
            if self.value == 'last':
                return indexAmongSiblings == totalSiblings - 1
            return indexAmongSiblings == self.value - 1
        return False

class _Step(object):
    __slots__ = ('tag', 'predicates')

    def __init__(self, tag, predicates):
        self.tag = tag
        self.predicates = predicates

def _splitSteps(expr):
    steps = []
    buf = []
    quote = None
    depth = 0
    for ch in expr:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth < 0:
                raise SelectorError('unbalanced ] in selector: %s' % expr)
        elif ch == '/' and depth == 0:
            steps.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    if quote is not None:
        raise SelectorError('unterminated %s quote in selector: %s'
                            % (quote, expr))
    if depth:
        raise SelectorError('unbalanced [ in selector: %s' % expr)
    steps.append(''.join(buf))
    return steps

splitSteps = _splitSteps

def parseSelector(expr):
    if not expr or not expr.strip():
        raise SelectorError('empty selector')
    steps = []
    for raw in _splitSteps(expr):
        raw = raw.strip()
        if not raw:
            raise SelectorError(
                'empty step in selector: %s (recursive descent // is not '
                'supported; use a fully-qualified path)' % expr)

        axisTag = None
        predPart = ''
        if raw == '.' or raw == '..':
            axisTag = raw
        elif raw.startswith('..[') or raw.startswith('.['):
            split = raw.index('[')
            axisTag = raw[:split]
            predPart = raw[split:]
            if axisTag not in ('.', '..'):
                raise SelectorError('invalid axis step: %s' % raw)
        if axisTag is not None:
            preds = []
            for pm in _PRED_RE.finditer(predPart):
                p = _parsePredicate(pm.group(1).strip())
                if p.kind == 'pos':
                    raise SelectorError(
                        "positional predicate not allowed on '%s' axis (%s)"
                        % (axisTag, raw))
                preds.append(p)
            steps.append(_Step(axisTag, preds))
            continue
        m = _STEP_RE.match(raw)
        if not m or m.end() != len(raw):
            raise SelectorError('invalid step: %s' % raw)
        tag, predPart = m.group(1), m.group(2)
        preds = []
        for pm in _PRED_RE.finditer(predPart):
            preds.append(_parsePredicate(pm.group(1).strip()))
        steps.append(_Step(tag, preds))
    return steps

def _parsePredicate(body):
    m = _ATTR_PRED_RE.match(body)
    if m:
        value = m.group(2) if m.group(2) is not None else m.group(3)
        return _Predicate('attr', m.group(1), value)
    m = _TEXT_PRED_RE.match(body)
    if m:
        value = m.group(1) if m.group(1) is not None else m.group(2)
        return _Predicate('text', None, value)
    m = _POS_PRED_RE.match(body)
    if m:
        token = m.group(1)
        if token == 'last()':
            return _Predicate('pos', None, 'last')
        return _Predicate('pos', None, int(token))
    raise SelectorError('unsupported predicate: [%s]' % body)

def findAll(rootNode, expr):
    steps = parseSelector(expr)
    current = [rootNode]
    for step in steps:
        if step.tag == '.':
            if step.predicates:
                current = [n for n in current
                           if all(p.matches(n, 0, 1) for p in step.predicates)]
            if not current:
                return []
            continue
        if step.tag == '..':
            parents = []
            seen = set()
            for n in current:
                p = getattr(n, 'parentNode', None)
                if p is None or getattr(p, 'nodeType', 0) != 1:
                    continue
                pid = id(p)
                if pid in seen:
                    continue
                seen.add(pid)
                parents.append(p)
            if step.predicates:
                parents = [p for p in parents
                           if all(pr.matches(p, 0, 1) for pr in step.predicates)]
            current = parents
            if not current:
                return []
            continue
        nextLevel = []
        for parent in current:
            candidates = _directElementChildren(parent, step.tag)
            total = len(candidates)
            for idx, child in enumerate(candidates):
                ok = True
                for pred in step.predicates:
                    if not pred.matches(child, idx, total):
                        ok = False
                        break
                if ok:
                    nextLevel.append(child)
        current = nextLevel
        if not current:
            return []
    return current

def findFirst(rootNode, expr):
    matches = findAll(rootNode, expr)
    return matches[0] if matches else None

def exists(rootNode, expr):
    return bool(findAll(rootNode, expr))

def _directElementChildren(parent, tag):
    out = []
    for child in parent.childNodes:
        if child.nodeType != 1:
            continue
        if tag == '*' or child.tagName == tag:
            out.append(child)
    return out

def _innerText(node):
    parts = []
    for child in node.childNodes:
        if child.nodeType == 3:
            parts.append(child.data)
    return ''.join(parts).strip()

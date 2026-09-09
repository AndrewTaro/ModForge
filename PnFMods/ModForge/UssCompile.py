# coding=utf-8

import Paths
from Codec import _u2

_CENSORED = ('ExternalInterface', 'GameDelegate', 'GameInfoHolder',
             'InputDelegate', 'gameInfoHolder', 'getDefinitionByName')

class CompileError(Exception):
    pass

def _modules():
    import AbcFmt
    import UssBuild
    import UssSwf
    import UssTrans
    import UssXml
    return AbcFmt, UssBuild, UssSwf, UssTrans, UssXml

def censoredStrings(poolStrings):
    hits = []
    for s in poolStrings:
        if not s:
            continue
        for entry in _CENSORED:
            if entry[:len(s)] == s:
                hits.append(s)
                break
    return hits

def compileMarkup(absXmlPaths):
    abcFmt, ussBuild, ussSwf, ussTrans, ussXml = _modules()

    collector = ussTrans.Collector()
    for path in absXmlPaths:
        try:
            data = Paths.readBytes(path)
        except Exception as exc:
            raise CompileError('cannot read %s: %s' % (path, exc))
        try:
            root = _u2.fromstring(data)
        except Exception as exc:
            raise CompileError('%s is not valid XML: %s' % (path, exc))
        ussXml.scan_element(root, collector)

    entries = collector.entries()
    abc = ussBuild.build_abc(entries)

    # ref:uss-censor
    hits = censoredStrings(abc['cpool']['strings'])
    if hits:
        raise CompileError(
            'the client blanks these strings in an unsigned SWF, so the '
            'compiled expressions would not behave as written: %s'
            % ', '.join(sorted(set(hits))))

    return ussSwf.build_swf(abcFmt.serialize_abc(abc)), len(entries)

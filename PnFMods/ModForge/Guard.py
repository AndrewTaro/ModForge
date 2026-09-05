# coding=utf-8

import Paths

def outputHashes(stagedPairs):
    return dict((rel, Paths.hashBytes(data)) for rel, data in stagedPairs)

def detectDrift(recordedHashes):
    drifted = []
    for rel, expected in sorted(recordedHashes.items()):
        absPath = Paths.resolveResModsTarget(rel)
        if absPath is None:
            continue
        if not Paths.fileExists(absPath):
            drifted.append((rel, 'missing'))
            continue
        try:
            actual = Paths.hashBytes(Paths.readBytes(absPath))
        except Exception as exc:
            drifted.append((rel, 'unreadable: %s' % exc))
            continue
        if actual != expected:
            drifted.append((rel, 'overwritten by something else'))
    return drifted

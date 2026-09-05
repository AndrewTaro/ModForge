# coding=utf-8

import Paths
from Logger import logError

class TransactionError(Exception):
    pass

class Transaction(object):
    def __init__(self):
        self._pending = {}

    def stage(self, absPath, newBytes):
        priorBytes = None
        if Paths.fileExists(absPath):
            try:
                priorBytes = Paths.readBytes(absPath)
            except Exception as exc:
                raise TransactionError(
                    'cannot snapshot %s before stage: %s' % (absPath, exc))
        self._pending[absPath] = (newBytes, priorBytes)

    def commit(self):
        if not self._pending:
            return
        written = []
        try:
            for absPath, (newBytes, _prior) in self._pending.items():
                self._atomicWrite(absPath, newBytes)
                written.append(absPath)
        except Exception as commitExc:
            logError('commit failed for %s: %s' % (written[-1] if written else '?',
                                                   commitExc))
            self._rollback(written)
            raise
        finally:
            self._sweepTempFiles(self._pending.keys())

            self._pending.clear()

    def _atomicWrite(self, absPath, data):
        Paths.ensureDir(Paths.dirName(absPath))
        tmpPath = absPath + '.new'
        Paths.removeFile(tmpPath)
        f = Paths.openWrite(tmpPath)
        try:
            f.write(data)
            f.flush()
        finally:
            f.close()
        Paths.renameFile(tmpPath, absPath)

    def _rollback(self, written):
        for absPath in written:
            _newBytes, prior = self._pending[absPath]
            try:
                if prior is None:
                    Paths.removeFile(absPath)
                else:
                    self._atomicWrite(absPath, prior)
            except Exception as exc:
                logError('rollback failed for %s: %s' % (absPath, exc))

    def _sweepTempFiles(self, absPaths):
        for absPath in absPaths:
            Paths.removeFile(absPath + '.new')

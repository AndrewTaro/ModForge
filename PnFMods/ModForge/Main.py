# coding=utf-8

API_VERSION = 'API_v1.0'
MOD_NAME = 'ModForge'

import time

from Installer import runInstaller
from Logger import logInfo, logError

__author__ = 'TTaro_'
INSTALLER_VERSION = '1.0.0'

def _run():
    startedAt = time.time()
    logInfo('%s starting (v%s)' % (MOD_NAME, INSTALLER_VERSION))
    logInfo('time: %s' % time.ctime())
    try:
        stats = runInstaller(INSTALLER_VERSION)
    except Exception as exc:
        logError('fatal: %s' % exc)
        raise
    elapsed = round(time.time() - startedAt, 2)
    logInfo(
        'done in %ss: discovered=%d installed=%d updated=%d '
        'unchanged=%d skipped=%d failed=%d removed=%d'
        % (elapsed, stats.discovered, stats.installed, stats.updated,
           stats.unchanged, stats.skipped, stats.failed, stats.removed))

_run()

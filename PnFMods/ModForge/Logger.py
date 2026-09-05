# coding=utf-8

MOD_NAME = 'ModForge'

def logInfo(*args):
    data = [str(i) for i in args]
    utils.logInfo('[{}] {}'.format(MOD_NAME, ', '.join(data)))

def logError(*args):
    data = [str(i) for i in args]
    utils.logError('[{}] {}'.format(MOD_NAME, ', '.join(data)))

def classFactory(iface):
    from .plugin import MulanjeHealthPlugin
    return MulanjeHealthPlugin(iface)

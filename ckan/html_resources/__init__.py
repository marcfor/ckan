''' This file creates fanstatic resources from the sub directories. The
directory can contain a config.ini to specify how the resources should
be treated. minified copies of the resources are created if the resource
has a later modification time than existing minified versions.

NOTE :currently each library requires its entry point adding to the main
ckan setup.py file.


config.ini (example)
==========
# all resources are named without their file extension
[main]
# dont_bundle prevents the resources from being bundled
dont_bundle = test1
# order can be used to prevent dependency errors to ensure that the
# needed resources are created first
order = test1 test2
[depends]
# resource dependencies can be specified here by listing dependent
# resources
test2 = test1
[groups]
# a group containing several resources can be specified here
test3 = test2 test1


'''
import os.path
import sys
import ConfigParser

from fanstatic import Library, Resource, Group, get_library_registry
import fanstatic.core as core
from ckan.include.rjsmin import jsmin
from ckan.include.rcssmin import cssmin

# TODO
# loop through dirs to setup
# warn on no entry point provided for fanstatic

class IEConditionalRenderer(object):
    ''' Allows for IE conditionals. '''
    def __init__(self, condition, renderer, other_browsers=False):
        self.condition = condition
        self.renderer = renderer
        self.other_browsers = other_browsers
        if other_browsers:
            self.other_browsers_start= '<!-->'
            self.other_browsers_end= '<!--'
        else:
            self.other_browsers_start= ''
            self.other_browsers_end= ''

    def __call__(self, url):
        return '<!--[if %s]>%s%s%s<![endif]-->' % (self.condition,
                                                   self.other_browsers_start,
                                                   self.renderer(url),
                                                   self.other_browsers_end)

# Fanstatic Patch #
# FIXME add full license info & push upstream
def __init__(self, library, relpath,
             depends=None,
             supersedes=None,
             bottom=False,
             renderer=None,
             debug=None,
             dont_bundle=False,
             minified=None):
    self.library = library
    fullpath = os.path.normpath(os.path.join(library.path, relpath))
    if core._resource_file_existence_checking and not os.path.exists(fullpath):
        raise core.UnknownResourceError("Resource file does not exist: %s" %
                                   fullpath)
    self.relpath = relpath
    self.dirname, self.filename = os.path.split(relpath)
    if self.dirname and not self.dirname.endswith('/'):
        self.dirname += '/'
    self.bottom = bottom
    self.dont_bundle = dont_bundle

    self.ext = os.path.splitext(self.relpath)[1]
    if renderer is None:
        # No custom, ad-hoc renderer for this Resource, so lookup
        # the default renderer by resource filename extension.
        if self.ext not in core.inclusion_renderers:
            raise core.UnknownResourceExtensionError(
                "Unknown resource extension %s for resource: %s" %
                (self.ext, repr(self)))
        self.order, self.renderer = core.inclusion_renderers[self.ext]
    else:
        # Use the custom renderer.
        self.renderer = renderer
        # If we do not know about the filename extension inclusion
        # order, we render the resource after all others.
        self.order, _ = core.inclusion_renderers.get(
            self.ext, (sys.maxint, None))

    assert not isinstance(depends, basestring)
    self.depends = set()
    if depends is not None:
        # Normalize groups into the underlying resources...
        depends = core.normalize_groups(depends)
        # ...before updating the set of dependencies of this resource.
        self.depends.update(depends)

    self.resources = set([self])
    for depend in self.depends:
        self.resources.update(depend.resources)

    # Check for library dependency cycles.
    self.library.check_dependency_cycle(self)

    # generate an internal number for sorting the resource
    # on dependency within the library
    self.init_dependency_nr()

    self.modes = {}
    for mode_name, argument in [(core.DEBUG, debug), (core.MINIFIED, minified)]:
        if argument is None:
            continue
        elif isinstance(argument, basestring):
            mode_resource = Resource(library, argument, bottom=bottom, renderer=renderer)
        else:
            # The dependencies of a mode resource should be the same
            # or a subset of the dependencies this mode replaces.
            if len(argument.depends - self.depends) > 0:
                raise core.ModeResourceDependencyError
            mode_resource = argument

        mode_resource.dependency_nr = self.dependency_nr
        self.modes[mode_name] = mode_resource

    assert not isinstance(supersedes, basestring)
    self.supersedes = supersedes or []

    self.rollups = []
    # create a reference to the superseder in the superseded resource
    for resource in self.supersedes:
        resource.rollups.append(self)
    # also create a reference to the superseding mode in the superseded
    # mode
    # XXX what if mode is full-fledged resource which lists
    # supersedes itself?
    for mode_name, mode in self.modes.items():
        for resource in self.supersedes:
            superseded_mode = resource.mode(mode_name)
            # if there is no such mode, let's skip it
            if superseded_mode is resource:
                continue
            mode.supersedes.append(superseded_mode)
            superseded_mode.rollups.append(mode)


    # Register ourself with the Library.
    self.library.register(self)

core.Resource.__init__ = __init__
# Fanstatic Patch #


def create_library(name, path):
    ''' Creates a fanstatic library `name` with the contents of a
    directory `path` using config.ini if found. Files are minified
    if needed. '''

    def min_path(path):
        ''' return the .min filename eg moo.js -> moo.min.js '''
        if f.endswith('.js'):
            return path[:-3] + '.min.js'
        if f.endswith('.css'):
            return path[:-4] + '.min.css'

    def minify(filename, min_function):
        ''' Minify file path using min_function. '''
        # if the minified file was modified after the source file we can
        # assume that it is up-to-date
        path = os.path.join(resource_path, filename)
        path_min = min_path(path)
        op = os.path
        if op.exists(path_min) and op.getmtime(path) < op.getmtime(path_min):
            return
        source = open(path, 'r').read()
        f = open(path_min, 'w')
        f.write(min_function(source))
        f.close()
        print 'minified %s' % path

    def create_resource(filename, path, filepath):
        ''' create the fanstatic Resource '''
        # resource_name is name of the file without the .js/.css
        resource_name = '.'.join(filename.split('.')[:-1])
        kw = {}
        path_min = min_path(os.path.join(resource_path, filename))
        if os.path.exists(path_min):
            kw['minified'] = min_path(filename)
        if filename.endswith('.js'):
            kw['bottom'] = True
            renderer = core.render_js
        if filename.endswith('.css'):
            renderer = core.render_css
        if resource_name in depends:
            dependencies = []
            for dependency in depends[resource_name]:
                dependencies.append(getattr(module, dependency))
            kw['depends'] = dependencies
        if resource_name in dont_bundle:
            kw['dont_bundle'] = True
        # FIXME needs config.ini options enabled
        if False:
            other_browsers = False
            condition = ''
            kw['renderer'] = IEConditionalRenderer(
                                        condition=condition,
                                        renderer=renderer,
                                        other_browsers=other_browsers)

        resource = Resource(library, filename, **kw)
        # add the resource to this module
        fanstatic_name = '%s/%s' % (filepath, resource_name)
        setattr(module, fanstatic_name, resource)

    order = []
    dont_bundle = []
    depends = {}
    groups = {}

    # parse the config.ini file if it exists
    resource_path = os.path.dirname(__file__)
    resource_path = os.path.join(resource_path, path)
    config_path = os.path.join(resource_path, 'config.ini')
    if os.path.exists(config_path):
        config = ConfigParser.RawConfigParser()
        config.read(config_path)
        if config.has_option('main', 'order'):
            order = config.get('main', 'order').split()
        if config.has_option('main', 'dont_bundle'):
            dont_bundle = config.get('main', 'dont_bundle').split()
        if config.has_section('depends'):
            items = config.items('depends')
            depends = dict((n, v.split()) for (n, v) in items)
        if config.has_section('groups'):
            items = config.items('groups')
            groups = dict((n, v.split()) for (n, v) in items)

    library = Library(name, path)
    module = sys.modules[__name__]

    # process each .js/.css file found
    for dirname, dirnames, filenames in os.walk(resource_path):
        for x in reversed(order):
            if x in filenames:
                filenames.remove(x)
                filenames.insert(0, x)
        for f in filenames:
            if f.endswith('.js') and not f.endswith('.min.js'):
                minify(f, jsmin)
                create_resource(f, resource_path, path)
            if f.endswith('.css') and not f.endswith('.min.css'):
                minify(f, cssmin)
                create_resource(f, resource_path, path)

    # add groups
    for group_name in groups:
        members = []
        for member in groups[group_name]:
            fanstatic_name = '%s/%s' % (path, member)
            members.append(getattr(module, fanstatic_name))
        group = Group(members)
        fanstatic_name = '%s/%s' % (path, group_name)
        setattr(module, fanstatic_name, group)
    # finally add the library to this module
    setattr(module, name, library)
    # add to fanstatic
    registry = get_library_registry()
    registry.add(library)


# create our libraries here from any subdirectories
for dirname, dirnames, filenames in os.walk(os.path.dirname(__file__)):
    if dirname == os.path.dirname(__file__):
        continue
    lib_name = os.path.basename(dirname)
    create_library(lib_name, lib_name)
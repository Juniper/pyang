"""YIN output plugin"""

from xml.sax.saxutils import quoteattr
from xml.sax.saxutils import escape

import optparse
import re
import sys

from .. import plugin
from .. import util
from .. import grammar
from .. import syntax
from .. import statements
from .. statements import has_children
from .. statements import expand_children

yin_namespace = "urn:ietf:params:xml:ns:yang:yin:1"

def pyang_plugin_init():
    plugin.register_plugin(YINPlugin())

class YINPlugin(plugin.PyangPlugin):
    def add_opts(self, optparser):
        optlist = [
            optparse.make_option("--yin-canonical",
                                 dest="yin_canonical",
                                 action="store_true",
                                 help="Print in canonical order"),
            optparse.make_option("--yin-pretty-strings",
                                 dest="yin_pretty_strings",
                                 action="store_true",
                                 help="Pretty print strings"),
            optparse.make_option("--yin-expand-groupings",
                                 dest="yin_expand_groupings",
                                 action="store_true",
                                 help="Expand groupings/uses in place"),
            ]
        g = optparser.add_option_group("YIN output specific options")
        g.add_options(optlist)
    def add_output_format(self, fmts):
        self.multiple_modules = True
        fmts['yin'] = self
    def emit(self, ctx, modules, fd):
        if len(modules) > 1 and not ctx.opts.yin_expand_groupings:
            sys.stderr.write("too many files to convert\n")
            sys.exit(1)

        module = modules[0]
        emit_yin(ctx, module, fd)

def emit_yin(ctx, module, fd):
    fd.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    fd.write('<%s name="%s"\n' % (module.keyword, module.arg))
    fd.write(' ' * len(module.keyword) + '  xmlns="%s"' % yin_namespace)

    prefix = module.search_one('prefix')
    if prefix is not None:
        namespace = module.search_one('namespace')
        fd.write('\n')
        fd.write(' ' * len(module.keyword))
        fd.write('  xmlns:' + prefix.arg + '=' +
                 quoteattr(namespace.arg))
    else:
        belongs_to = module.search_one('belongs-to')
        if belongs_to is not None:
            prefix = belongs_to.search_one('prefix')
            if prefix is not None:
                # read the parent module in order to find the namespace uri
                res = ctx.read_module(belongs_to.arg, extra={'no_include':True})
                if res is not None:
                    namespace = res.search_one('namespace')
                    if namespace is None or namespace.arg is None:
                        pass
                    else:
                        # success - namespace found
                        fd.write('\n')
                        fd.write(' ' * len(module.keyword))
                        fd.write('  xmlns:' + prefix.arg + '=' +
                                 quoteattr(namespace.arg))

    for imp in module.search('import'):
        prefix = imp.search_one('prefix')
        if prefix is not None:
            rev = None
            r = imp.search_one('revision-date')
            if r is not None:
                rev = r.arg
            mod = statements.modulename_to_module(module, imp.arg, rev)
            if mod is not None:
                ns = mod.search_one('namespace')
                if ns is not None:
                    fd.write('\n')
                    fd.write(' ' * len(module.keyword))
                    fd.write('  xmlns:' + prefix.arg + '=' +
                             quoteattr(ns.arg))
    fd.write('>\n')

    skip = []
    if ctx.opts.yin_expand_groupings:
        mods = [module]
        for i in module.search('include'):
            subm = ctx.get_module(i.arg)
            if subm is not None:
                mods.append(subm)

        for m in mods:
            for augment in m.search('augment'):
                if (hasattr(augment, 'i_target_node') and
                    hasattr(augment.i_target_node, 'i_module') and
                    augment.i_target_node.i_module not in mods):

                    fd.write("<!-- augment {} -->\n".format(augment.arg))
                    skip.append(augment)

    substmts = module.substmts
    if ctx.opts.yin_expand_groupings and has_children(module):
        substmts = expand_children(ctx, module)

    if ctx.opts.yin_canonical:
        substmts = grammar.sort_canonical(module.keyword, substmts)

    for s in substmts:
        if s not in skip:
            emit_stmt(ctx, module, s, fd, '  ', '  ')
    fd.write('</%s>\n' % module.keyword)

def emit_stmt(ctx, module, stmt, fd, indent, indentstep):
    if util.is_prefixed(stmt.raw_keyword):
        # this is an extension.  need to find its definition
        (prefix, identifier) = stmt.raw_keyword
        tag = prefix + ':' + identifier
        if stmt.i_extension is not None:
            ext_arg = stmt.i_extension.search_one('argument')
            if ext_arg is not None:
                yin_element = ext_arg.search_one('yin-element')
                if yin_element is not None and yin_element.arg == 'true':
                    argname = prefix + ':' + ext_arg.arg
                    argiselem = True
                else:
                    # explicit false or no yin-element given
                    argname = ext_arg.arg
                    argiselem = False
            else:
                argiselem = False
                argname = None
        else:
            argiselem = False
            argname = None
    else:
        (argname, argiselem) = syntax.yin_map[stmt.raw_keyword]
        tag = stmt.raw_keyword

    substmts = stmt.substmts
    if argiselem is False or argname is None:
        if argname is None:
            attr = ''
        else:
            attr = ' ' + argname + '=' + quoteattr(stmt.arg)

        if ctx.opts.yin_expand_groupings and has_children(stmt):
            substmts = expand_children(ctx, stmt)

        if len(substmts) == 0:
            fd.write(indent + '<' + tag + attr + '/>\n')
        else:
            fd.write(indent + '<' + tag + attr + '>\n')
            for s in substmts:
                emit_stmt(ctx, module, s, fd, indent + indentstep,
                          indentstep)
            fd.write(indent + '</' + tag + '>\n')
    else:
        fd.write(indent + '<' + tag + '>\n')
        if ctx.opts.yin_pretty_strings:
            # since whitespace is significant in XML, the current
            # code is strictly speaking incorrect.  But w/o the whitespace,
            # it looks too ugly.
            fd.write(indent + indentstep + '<' + argname + '>\n')
            fd.write(fmt_text(indent + indentstep + indentstep, stmt.arg))
            fd.write('\n' + indent + indentstep + '</' + argname + '>\n')
        else:
            fd.write(indent + indentstep + '<' + argname + '>' + \
                       escape(stmt.arg) + \
                       '</' + argname + '>\n')
        if ctx.opts.yin_canonical:
            substmts = grammar.sort_canonical(stmt.keyword, substmts)

        for s in substmts:
            emit_stmt(ctx, module, s, fd, indent + indentstep, indentstep)
        fd.write(indent + '</' + tag + '>\n')

def fmt_text(indent, data):
    res = []
    for line in re.split("(\n)", escape(data)):
        if line == '':
            continue
        if line == '\n':
            res.extend(line)
        else:
            res.extend(indent + line)
    return ''.join(res)

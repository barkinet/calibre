#!/usr/bin/env python
# vim:fileencoding=utf-8
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'

import textwrap
from future_builtins import map

# from lxml.etree import Element

from calibre import force_unicode
from calibre.ebooks.oeb.base import (
    serialize, OEB_DOCS, barename, OEB_STYLES, XPNSMAP, XHTML, SVG)
from calibre.ebooks.oeb.polish.container import OPF_NAMESPACES, guess_type
from calibre.utils.icu import sort_key

def isspace(x):
    return not x.strip('\u0009\u000a\u000c\u000d\u0020')

def pretty_xml_tree(elem, level=0, indent='  '):
    ''' XML beautifier, assumes that elements that have children do not have
    textual content.  Also assumes that there is no text immediately after
    closing tags. These are true for opf/ncx and container.xml files. If either
    of the assumptions are violated, there should be no data loss, but pretty
    printing wont produce optimal results.'''
    if (not elem.text and len(elem) > 0) or (elem.text and isspace(elem.text)):
        elem.text = '\n' + (indent * (level+1))
    for i, child in enumerate(elem):
        pretty_xml_tree(child, level=level+1, indent=indent)
        if not child.tail or isspace(child.tail):
            l = level + 1
            if i == len(elem) - 1:
                l -= 1
            child.tail = '\n' + (indent * l)

def pretty_opf(root):
    # Put all dc: tags first starting with title and author. Preserve order for
    # the rest.
    def dckey(x):
        return {'title':0, 'creator':1}.get(barename(x.tag), 2)
    for metadata in root.xpath('//opf:metadata', namespaces=OPF_NAMESPACES):
        dc_tags = metadata.xpath('./*[namespace-uri()="%s"]' % OPF_NAMESPACES['dc'])
        dc_tags.sort(key=dckey)
        for x in reversed(dc_tags):
            metadata.insert(0, x)

    # Group items in the manifest
    spine_ids = root.xpath('//opf:spine/opf:itemref/@idref', namespaces=OPF_NAMESPACES)
    spine_ids = {x:i for i, x in enumerate(spine_ids)}

    def manifest_key(x):
        mt = x.get('media-type', '')
        href = x.get('href', '')
        ext = href.rpartition('.')[-1].lower()
        cat = 1000
        if mt in OEB_DOCS:
            cat = 0
        elif mt == guess_type('a.ncx'):
            cat = 1
        elif mt in OEB_STYLES:
            cat = 2
        elif mt.startswith('image/'):
            cat = 3
        elif ext in {'otf', 'ttf', 'woff'}:
            cat = 4
        elif mt.startswith('audio/'):
            cat = 5
        elif mt.startswith('video/'):
            cat = 6

        if cat == 0:
            i = spine_ids.get(x.get('id', None), 1000000000)
        else:
            i = sort_key(href)
        return (cat, i)

    for manifest in root.xpath('//opf:manifest', namespaces=OPF_NAMESPACES):
        children = sorted(manifest, key=manifest_key)
        for x in reversed(children):
            manifest.insert(0, x)

SVG_TAG = SVG('svg')

BLOCK_TAGS = frozenset(map(XHTML, (
    'address', 'article', 'aside', 'audio', 'blockquote', 'body', 'canvas', 'dd',
    'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li',
    'noscript', 'ol', 'output', 'p', 'pre', 'script', 'section', 'style', 'table', 'tbody', 'td',
    'tfoot', 'thead', 'tr', 'ul', 'video'))) | {SVG_TAG}


def isblock(x):
    if callable(x.tag) or not x.tag:
        return True
    if x.tag in BLOCK_TAGS:
        return True
    return False

def has_only_blocks(x):
    if hasattr(x.tag, 'split') and len(x) == 0:
        # Tag with no children,
        return False
    if x.text and not isspace(x.text):
        return False
    for child in x:
        if not isblock(child) or (child.tail and isspace(child.tail)):
            return False
    return True

def indent_for_tag(x):
    prev = x.getprevious()
    x = x.getparent().text if prev is None else prev.tail
    if not x:
        return None
    s = x.rpartition('\n')[-1]
    return s if isspace(s) else None

def set_indent(elem, attr, indent):
    x = getattr(elem, attr)
    if not x:
        x = indent
    else:
        lines = x.splitlines()
        if isspace(lines[-1]):
            lines[-1] = indent
        else:
            lines.append(indent)
        x = '\n'.join(lines)
    setattr(elem, attr, x)

def pretty_block(parent, level=1, indent='  '):
    ''' Surround block tags with blank lines and recurse into child block tags
    that contain only other block tags '''
    if not parent.text or isspace(parent.text):
        parent.text = ''
    nn = '\n' if hasattr(parent.tag, 'strip') and barename(parent.tag) in {'tr', 'td', 'th'} else '\n\n'
    parent.text = parent.text + nn + (indent * level)
    for i, child in enumerate(parent):
        if isblock(child) and has_only_blocks(child):
            pretty_block(child, level=level+1, indent=indent)
        elif child.tag == SVG_TAG:
            pretty_xml_tree(child, level=level, indent=indent)
        l = level
        if i == len(parent) - 1:
            l -= 1
        if not child.tail or isspace(child.tail):
            child.tail = ''
        child.tail = child.tail + nn + (indent * l)

def pretty_html_tree(container, root):
    root.text = '\n\n'
    for child in root:
        child.tail = '\n\n'
        if hasattr(child.tag, 'endswith') and child.tag.endswith('}head'):
            pretty_xml_tree(child)
    for body in root.findall('h:body', namespaces=XPNSMAP):
        pretty_block(body)

    # Handle <script> and <style> tags
    for child in root.xpath('//*[local-name()="script" or local-name()="style"]'):
        if child.text:
            indent = indent_for_tag(child)
            if child.tag.endswith('style'):
                child.text = force_unicode(pretty_css(container, '', child.text), 'utf-8')
            child.text = textwrap.dedent(child.text)
            child.text = '\n' + '\n'.join([(indent + x) if x else '' for x in child.text.splitlines()])
            set_indent(child, 'text', indent)

def fix_html(container, raw):
    root = container.parse_xhtml(raw)
    return serialize(root, 'text/html')

def pretty_html(container, name, raw):
    root = container.parse_xhtml(raw)
    pretty_html_tree(container, root)
    return serialize(root, 'text/html')

def pretty_css(container, name, raw):
    sheet = container.parse_css(raw)
    return serialize(sheet, 'text/css')

def pretty_xml(container, name, raw):
    root = container.parse_xml(raw)
    if name == container.opf_name:
        pretty_opf(root)
    pretty_xml_tree(root)
    return serialize(root, 'text/xml')

def fix_all_html(container):
    for name, mt in container.mime_map.iteritems():
        if mt in OEB_DOCS:
            container.parsed(name)
            container.dirty(name)

def pretty_all(container):
    for name, mt in container.mime_map.iteritems():
        prettied = False
        if mt in OEB_DOCS:
            pretty_html_tree(container, container.parsed(name))
            prettied = True
        elif mt in OEB_STYLES:
            container.parsed(name)
            prettied = True
        elif name == container.opf_name:
            root = container.parsed(name)
            pretty_opf(root)
            pretty_xml_tree(root)
            prettied = True
        elif mt in {guess_type('a.ncx'), guess_type('a.xml')}:
            pretty_xml_tree(container.parsed(name))
            prettied = True
        if prettied:
            container.dirty(name)


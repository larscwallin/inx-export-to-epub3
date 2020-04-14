# This file is part of EbookLib.
# Copyright (c) 2013 Aleksandar Erkalovic <aerkalov@gmail.com>
#
# EbookLib is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# EbookLib is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with EbookLib.  If not, see <http://www.gnu.org/licenses/>.
import sys

sys.path.append('./ebooklib')

import six
from ebooklib.epub import EpubItem

try:
    from urllib.parse import unquote
except ImportError:
    from urllib import unquote

from lxml import etree

import ebooklib

from ebooklib.utils import parse_string, parse_html_string

class InxEpubBook(ebooklib.epub.EpubBook):

    def __init__(self):
        super(InxEpubBook, self).__init__()


class InxEpubItem(ebooklib.epub.EpubItem):
    """
    Base class for the items in a book.
    """

    def __init__(self, uid=None, file_name='', media_type='', content=six.b(''), manifest=True, create=True):
        super(InxEpubItem, self).__init__(uid=uid, file_name=file_name, media_type=media_type, content=content, manifest=manifest)

        self.id = uid
        self.file_name = file_name
        self.media_type = media_type
        self.content = content
        self.is_linear = True
        self.manifest = manifest

        self.book = None
        self.create = create


class InxEpubHtml(InxEpubItem):

    """
    Represents HTML document in the EPUB file.
    """
    _template_name = 'chapter'

    def __init__(self, uid=None, file_name='', media_type='', content=None, title='',
                 lang=None, direction=None, media_overlay=None, media_duration=None, width=None, height=None):
        super(InxEpubHtml, self).__init__(uid=uid, file_name=file_name, media_type=media_type, content=content)

        self.title = title
        self.lang = lang
        self.direction = direction

        self.media_overlay = media_overlay
        self.media_duration = media_duration

        self.links = []
        self.properties = []
        self.pages = []

        self.width = width
        self.height = height


    def get_content(self, default=None):
        """
        Returns content for this document as HTML string. Content will be of type 'str' (Python 2)
        or 'bytes' (Python 3).

        :Args:
          - default: Default value for the content if it is not defined.

        :Returns:
          Returns content of this document.
        """

        tree = parse_string(self.book.get_template(self._template_name))
        tree_root = tree.getroot()

        tree_root.set('lang', self.lang or self.book.language)
        tree_root.attrib['{%s}lang' % ebooklib.epub.NAMESPACES['XML']] = self.lang or self.book.language

        # add to the head also
        #  <meta charset="utf-8" />

        try:
            html_tree = parse_html_string(self.content)
        except:
            return ''

        html_root = html_tree.getroottree()

        # create and populate head

        _head = etree.SubElement(tree_root, 'head')

        if self.title != '':
            _title = etree.SubElement(_head, 'title')
            _title.text = self.title

        if self.width and self.height:
            _viewport = etree.SubElement(_head, 'meta')
            _viewport.set('name', 'viewport')
            _viewport.set('content', 'width=' + str(self.width) + ', height=' + str(self.height))

        for lnk in self.links:
            if lnk.get('type') == 'text/javascript':
                _lnk = etree.SubElement(_head, 'script', lnk)
                # force <script></script>
                _lnk.text = ''
            else:
                _lnk = etree.SubElement(_head, 'link', lnk)

        # this should not be like this
        # head = html_root.find('head')
        # if head is not None:
        #     for i in head.getchildren():
        #         if i.tag == 'title' and self.title != '':
        #             continue
        #         _head.append(i)

        # create and populate body

        _body = etree.SubElement(tree_root, 'body')
        if self.direction:
            _body.set('dir', self.direction)
            tree_root.set('dir', self.direction)

        body = html_tree.find('body')
        if body is not None:
            for i in body.getchildren():
                _body.append(i)

        tree_str = etree.tostring(tree, pretty_print=True, encoding='utf-8', xml_declaration=True)

        return tree_str

    def __str__(self):
        return '<EpubHtml:%s:%s>' % (self.id, self.file_name)


class InxEpubSvg(InxEpubHtml):
    """
    Represents SVG document in the EPUB file.
    """

    def __init__(self, uid=None, file_name='', media_type='', content=None, title='', lang=None, direction=None, media_overlay=None, media_duration=None, width=None, height=None):
        super(InxEpubSvg, self).__init__(uid=uid, file_name=file_name, media_type=media_type, content=content)

        self.title = title
        self.lang = lang
        self.direction = direction

        self.media_overlay = media_overlay
        self.media_duration = media_duration

        self.links = []
        self.properties = []
        self.pages = []

        self.width = width
        self.height = height

    def get_body_content(self):
        return self.content

    def get_content(self, default=None):
        """
        Returns content for this document as SVG string. Content will be of type 'str' (Python 2)
        or 'bytes' (Python 3).

        :Args:
          - default: Default value for the content if it is not defined.

        :Returns:
          Returns content of this document.
        """

        return self.content

    def __str__(self):
        return '<EpubSvg:%s:%s>' % (self.id, self.file_name)


class InxEpubWriter(ebooklib.epub.EpubWriter):

    def __init__(self, name, book, options=None):
        super(InxEpubWriter, self).__init__(name, book, options=None)

        self.file_name = name
        self.book = book

        self.options = dict(self.DEFAULT_OPTIONS)
        if options:
            self.options.update(options)

    def _write_items(self):
        for item in self.book.get_items():
            if not hasattr(item, 'create') or item.create:
                if isinstance(item, ebooklib.epub.EpubNcx):
                    self.out.writestr('%s/%s' % (self.book.FOLDER_NAME, item.file_name), self._get_ncx())
                elif isinstance(item, ebooklib.epub.EpubNav):
                    self.out.writestr('%s/%s' % (self.book.FOLDER_NAME, item.file_name), self._get_nav(item))
                elif item.manifest:
                    self.out.writestr('%s/%s' % (self.book.FOLDER_NAME, item.file_name), item.get_content())
                else:
                    self.out.writestr('%s' % item.file_name, item.get_content())


def write_epub(name, book, options=None):
    """
    Creates epub file with the content defined in EpubBook.

    >>> ebooklib.write_epub('book.epub', book)

    :Args:
      - name: file name for the output file
      - book: instance of EpubBook
      - options: extra opions as dictionary (optional)
    """
    epub = InxEpubWriter(name, book, options)

    epub.process()

    try:
        epub.write()
    except IOError:
        pass

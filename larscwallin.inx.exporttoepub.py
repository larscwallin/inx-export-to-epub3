#!/usr/bin/env python

"""
    MIT License

    Copyright (c) 2020 Lars C Wallin <larscwallin@gmail.com>

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""

import base64
import copy
import sys
import urllib.parse
import urllib.request
import os
from pathlib import Path

from lxml import etree
from builtins import str

sys.path.append('./')
sys.path.append('./inkex')
sys.path.append('./scour')
sys.path.append('./ebooklib')

import re
import inkex
import scour.scour
import ebooklib
import larscwallin_inx_ebooklib_epub as inx_epub


class ExportToEpub(inkex.Effect):

    svg_src_template = """<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{{viewport.width}}" height="{{viewport.height}}" viewBox="0 0 {{document.width}} {{document.height}}" xml:space="preserve" preserveAspectRatio="xMinYMin">
    <title>{{title}}</title>
    <style id="font-declarations">
        {{font-faces}}
    </style>
    {{defs}}
    {{scripts}}
    <metadata xmlns="http://www.w3.org/2000/svg" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cc="http://creativecommons.org/ns#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:svg="http://www.w3.org/2000/svg" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" id="metadata5">
        <rdf:RDF>
            <dc:format>image/svg+xml</dc:format>
            <dc:type rdf:resource="http://purl.org/dc/dcmitype/StillImage"/>
            <dc:title>{{title}}</dc:title>
        </rdf:RDF>
    </metadata>
    {{element.source}}
</svg>"""

    font_face_template = """
    @font-face {
      font-family: {{font.family}};
      src: url("{{font.url}}");
    }
    """

    def __init__(self):
        inkex.Effect.__init__(self)

        self.arg_parser.add_argument('--where', action='store',
                                     type=str, dest='where', default='',
                                     help='Where to save the EPUB.')

        self.arg_parser.add_argument('--root_folder', action='store',
                                     type=str, dest='root_folder', default='',
                                     help='Project root folder path')

        self.arg_parser.add_argument('--filename', action='store',
                                     type=str, dest='filename', default='publication.epub',
                                     help='File name including extension.')

        self.arg_parser.add_argument('--resources_folder', action='store',
                                     type=str, dest='resources_folder', default='',
                                     help='Optional relative path to a folder containing additional '
                                          'resources to be added to the EPUB. Could be audio, video etc.')

        self.arg_parser.add_argument('--bottom_layer_as_cover', action='store',
                                     type=inkex.Boolean, dest='bottom_layer_as_cover', default=False,
                                     help='Use bottom layer as cover image?')

        self.arg_parser.add_argument('--wrap_svg_in_html', action='store',
                                     type=inkex.Boolean, dest='wrap_svg_in_html', default=False,
                                     help='Save documents as HTML instead of SVG?')

    def effect(self):
        self.publication_title = "Publication Title"
        self.publication_desc = ""
        # The output path for the created EPUB
        self.destination_path = self.options.where
        # The project root folder
        self.root_folder = self.options.root_folder
        # the resource folder is the location, relative to the project root folder, where the all the images, fonts etc
        # are stored. If you want a file to be automatically added to the EPUB it needs to be put in this folder.
        self.resources_folder = self.options.resources_folder
        self.filename = self.options.filename
        self.resource_items = []
        self.bottom_layer_as_cover = self.options.bottom_layer_as_cover
        self.wrap_svg_in_html = self.options.wrap_svg_in_html
        self.svg_doc = self.document.xpath('//svg:svg', namespaces=inkex.NSS)[0]
        self.svg_doc_width = float(self.svg.unittouu(self.svg_doc.get('width')))
        self.svg_doc_height = float(self.svg.unittouu(self.svg_doc.get('height')))
        self.svg_viewport_width = float(self.svg.unittouu(self.svg_doc.get('width')))
        self.svg_viewport_height = float(self.svg.unittouu(self.svg_doc.get('height')))
        self.svg_nav_doc = ebooklib.epub.EpubNav()

        # We only care about the "root layers" that are visible. Sub-layers will be included.
        self.visible_layers = self.document.xpath('/svg:svg/svg:g[not(contains(@style,"display:none"))]',
                                                  namespaces=inkex.NSS)
        # Create a new EPUB instance
        self.book = ebooklib.epub.EpubBook()

        if self.visible_layers.__len__() > 0:
            selected_layers = []
            content_documents = []

            # Get all defs elements. These are "injected" in each of the documents
            defs = self.document.xpath('//svg:svg/svg:defs', namespaces=inkex.NSS)
            defs_string = ''

            # Get all script elements in the document root. These are "injected" in each of the documents.
            # Script elements that are children of layers are unique to each document.
            scripts = self.document.xpath('//svg:svg/svg:script', namespaces=inkex.NSS)
            scripts_string = ''

            # We get all text elements in order to later get all used font-families.
            text_elements = self.document.xpath('//svg:text', namespaces=inkex.NSS)
            font_families = {}
            font_faces_string = ''

            resource_folder_path = os.path.join(self.root_folder, self.resources_folder)
            # Call add_resources to recursively add resources to the EPUB instance.
            self.add_resources(resource_folder_path)

            # Now let's go through the text elements and see which font families that are used.
            for text in text_elements:
                style = inkex.Style(text.get('style'))

                if style['font-family']:
                    font = style['font-family']
                    if font not in font_families:
                        font_families[font] = font

            # Time to loop through the script elements if there are any
            if len(scripts) > 0:

                for script in scripts:
                    xlink = script.get('xlink:href')

                    # If there is an xlink attribute it's an external script. External scripts are handled a
                    # bit differently than other resources. Instead of assuming that they are located in the
                    # specified resource folder they will be retrieved and put in the "scripts" folder in the
                    # root of the EPUB. I made this choice to make it easier to point to js on the web.
                    # Might change this later.

                    if xlink:

                        # Now we'll try to read the contents of the script file.
                        script_source = self.read_file(xlink)

                        if script_source is not None:

                            script_name = os.path.basename(xlink)
                            script_item = inx_epub.InxEpubItem(file_name=('scripts/' + script_name),
                                                        media_type='text/javascript', content=script_source)
                            self.book.add_item(script_item)

                            # Scripts should really use xlink:href but scour crashes if I use it :/
                            # src seems to work, but it does not validate
                            scripts_string += str(
                                    '<script src="' + ('scripts/' + script_name) + '"></script>')
                    else:
                        # If there is no xlink we can assume that this is an embedded script and grab its text content.
                        script_source = script.text
                        if script_source:
                            scripts_string += str(
                                '<script id="' + script.get('id') + '">' + script_source + '</script>')

            else:
                # No scripts so we just add a self closing element
                scripts_string = '<script />'

            # If we found defs we loop through them and add them to string which will be inserted in every document.
            # Note that we use Scour later for each doc to remove unused defs.
            if len(defs) > 0:
                for element in defs:
                    defs_string += str(etree.tostring(element, method='html', pretty_print=False), 'utf-8')
            else:
                defs_string = '<defs/>'

            metadata = self.document.xpath('//svg:svg/svg:metadata/rdf:RDF/cc:Work', namespaces=inkex.NSS)

            metadata_items = {
                'title': '',
                'date': '',
                'creator': '',
                'rights': '',
                'publisher': '',
                'description': '',
                'contributor': '',
                'language': ''
            }

            if len(metadata[0]) > 0:
                for element in metadata[0]:
                    # Copy the node to make sure that the input document is not mutated when we remove namespaces
                    element_copy = copy.deepcopy(element)
                    # Me being lazy. Flatten any metadata item to only include text
                    element_copy_text = element_copy.xpath(".//text()")
                    element_copy_text = ''.join(element_copy_text).strip() if len(element_copy_text) > 0 else ''
                    self.remove_namespace(element_copy, 'http://purl.org/dc/elements/1.1/')
                    self.remove_namespace(element_copy, 'http://www.w3.org/2000/svg')
                    metadata_items[element_copy.tag] = element_copy_text
                    element_copy = None
            else:
                pass

            if metadata_items['title'] != '':
                self.publication_title = metadata_items['title']
                self.book.set_title(self.publication_title)

            if metadata_items['description'] != '':
                self.publication_desc = metadata_items['description']

            # Add collected metadata to the book
            for term, val in metadata_items.items():
                if val != '':
                    self.book.add_metadata('DC', term, val)

            self.book.add_metadata(None, 'meta', 'pre-paginated', {'property': 'rendition:layout'})
            self.book.add_metadata(None, 'meta', 'auto', {'property': 'rendition:orientation'})

            # All visible layers will be saved as FXL docs in the EPUB. Let's loop through them!
            for element in self.visible_layers:

                # Save all images to the epub package
                self.save_images_to_epub(element, self.book)

                element_label = str(element.get(inkex.utils.addNS('label', 'inkscape'), ''))
                element_id = element.get('id').replace(' ', '_')

                if element_label != '':
                    element.set('label', element_label)
                    element.set('class', element_label)
                else:
                    pass

                element_source = etree.tostring(element, pretty_print=True)

                if element_source != '':
                    # Wrap the node in an SVG doc
                    tpl_result = str.replace(self.svg_src_template, '{{defs}}', defs_string)
                    tpl_result = str.replace(tpl_result, '{{scripts}}', scripts_string)
                    tpl_result = str.replace(tpl_result, '{{title}}', element_label)
                    tpl_result = str.replace(tpl_result, '{{viewport.width}}', str(self.svg_viewport_width))
                    tpl_result = str.replace(tpl_result, '{{viewport.height}}', str(self.svg_viewport_height))
                    tpl_result = str.replace(tpl_result, '{{document.width}}', str(self.svg_doc_width))
                    tpl_result = str.replace(tpl_result, '{{document.height}}', str(self.svg_doc_height))
                    tpl_result = str.replace(tpl_result, '{{element.source}}', str(element_source, 'utf-8'))

                    for font in font_families:
                        font_family = str.replace(font, ' ', '+')
                        font_family = str.replace(font_family, "'", '')

                        tpl_result = str.replace(tpl_result, font, font_family)

                        resource_path = os.path.join(self.root_folder, self.resources_folder)
                        font_file_name = self.find_file_fuzzy(font_family, resource_path)

                        if font_file_name is not None:
                            font_path = self.get_relative_resource_path(font_file_name)
                            font_tpl_result = str.replace(self.font_face_template, '{{font.family}}', font_family)
                            font_tpl_result = str.replace(font_tpl_result, '{{font.url}}', font_path)

                            font_faces_string = font_faces_string + font_tpl_result
                        else:
                            inkex.utils.debug('Could not find matching font file ' + font_family + ' in location ' + resource_path)

                    tpl_result = str.replace(tpl_result, '{{font-faces}}', font_faces_string)

                    font_faces_string = ''

                    tpl_result = self.scour_doc(tpl_result)

                    # TODO: Add processing instsruction to head of file
                    content_doc = etree.fromstring(tpl_result)
                    content_doc = etree.ElementTree(content_doc)

                    # If the result of the operation is valid, add the SVG source to the selected array
                    if tpl_result:
                        selected_layers.append({
                            'id': element_id,
                            'label': element_label,
                            'source': etree.tostring(content_doc, pretty_print=True),
                            'element': element
                        })

            for layer in selected_layers:
                # Cache these in local vars
                content = layer['source']
                label = layer['label'] or layer['id']
                label = label.replace(' ', '_')

                if content != '':

                    if self.wrap_svg_in_html:
                        doc = inx_epub.InxEpubHtml(uid=label, file_name=label + '.html', media_type='text/html',
                                            content=content, width=self.svg_viewport_width, height=self.svg_viewport_height)

                        content_documents.append(doc)

                        self.book.toc.append(ebooklib.epub.Link(label + '.html', label, layer['id']))

                    else:
                        content_documents.append(
                            inx_epub.InxEpubSvg(uid=label, file_name=label + '.svg', media_type="image/svg+xml",
                                         content=content))
                else:
                    pass

            # Skip cover image for now. To be implemented later.
            """
            if self.bottom_layer_as_cover:
                cover = content_documents[0]
                cover.content = re.subn(r'(?s)<(script).*?</\1>', '', cover.content.decode('utf-8'))[0]
                cover.properties.append('cover-image')
                try:
                    cover.properties.remove('scripted')
                except:
                    pass

                self.book.add_metadata(None, 'meta', '', inkex.OrderedDict([('name', 'cover'), ('content', cover.id)]))
                self.book.set_cover('cover.xhtml', cover.content, create_page=False)
            else:
                cover_content = '<html><head><title>' + str(self.publication_title) + '</title></head><body><h1>' + str(
                    self.publication_title) + '</h1></body></html>'
                self.book.set_cover('cover.xhtml', cover_content, create_page=False)
            """

            for doc in content_documents:

                if len(scripts) > 0 and 'cover-image' not in doc.properties:
                    doc.properties.append('scripted')

                # add manifest item
                self.book.add_item(doc)

                # add spine item
                self.book.spine.append(doc)

            self.svg_nav_doc
            self.book.add_item(self.svg_nav_doc)

            inx_epub.write_epub((self.destination_path + '/' + self.filename), self.book, {})

            inkex.utils.debug('Saved EPUB file to ' + (self.destination_path + '/' + self.filename))

        else:
            inkex.utils.debug('No SVG elements or layers to export')

        # End of effect() method

    def add_resources(self, folder=None):
        if folder is None:
            folder = self.resources_folder

        if os.path.isdir(folder):
            for resource in os.listdir(folder):
                resource_path = os.path.join(folder, resource)
                if os.path.isdir(resource_path):
                    self.add_resources(resource_path)
                else:
                    resource_content = self.read_file(resource_path, True)
                    if resource_content is not None:
                        rel_path = self.get_relative_resource_path(resource_path)

                        item = inx_epub.InxEpubItem(file_name=rel_path, content=resource_content)
                        self.book.add_item(item)

                    else:
                        inkex.utils.debug('"' + resource + '" is empty')
        else:
            inkex.utils.debug('"' + folder + '" is not a folder')

    def get_tag_name(self, node, ns='sodipodi'):
        type = node.get(inkex.utils.addNS('type', ns))

        if type is None:
            # remove namespace data {....}
            tag_name = node.tag
            tag_name = tag_name.split('}')[1]
        else:
            tag_name = str(type)

        return tag_name

    def scour_doc(self, str):
        return scour.scour.scourString(str).encode("UTF-8")

    def find_file_fuzzy(self, name, folder):
        folder = Path(folder)
        files = folder.rglob('*' + name + '*.*')
        for file in files:
            return str(file)

        return None

    def get_relative_resource_path(self, resource_path):
        rel_path = str.split(resource_path, self.root_folder)[1]
        return str.replace(rel_path.lstrip('/\\'), '\\', '/')

    def read_file(self, filename, binary=False):

        if urllib.parse.urlparse(filename).scheme in ('http', 'https'):
            response = urllib.request.urlopen(filename)
            contents = response.read()
            if contents:
                return contents
            else:
                return None
        else:
            if not binary:
                file = open(filename, 'r')
            else:
                file = open(filename, 'rb')

            if file:
                contents = file.read()
                file.close()
                return contents
            else:
                return None

    def save_to_file(self, content, filename):

        file = open(filename, 'w')

        if file:
            file.write(content)
            file.close()
            return True
        else:
            return False

    def remove_namespace(self, doc, namespace):
        """Remove namespace in the passed document in place."""
        ns = u'{%s}' % namespace
        nsl = len(ns)
        for elem in doc.getiterator():
            if elem.tag.startswith(ns):
                elem.tag = elem.tag[nsl:]
            else:
                pass

    def embed_all_images(self, element):
        path = '//svg:image'
        for node in element.xpath(path, namespaces=inkex.NSS):
            self.embed_image(node)

    def embed_image(self, node):
        """Embed the data of the selected Image Tag element"""
        xlink = node.get('xlink:href')
        if xlink and xlink[:5] == 'data:':
            # No need, data alread embedded
            return

        url = urllib.parse.urlparse(xlink)
        href = urllib.request.url2pathname(url.path)

        # Primary location always the filename itself.
        path = self.absolute_href(href or '')

        # Backup directory where we can find the image
        if not os.path.isfile(path):
            path = node.get('sodipodi:absref', path)

        if not os.path.isfile(path):
            inkex.errormsg('File not found "{}". Unable to embed image.'.format(path))
            return

        with open(path, "rb") as handle:
            # Don't read the whole file to check the header
            file_type = self.get_image_type(path, handle.read(10))
            handle.seek(0)

            if file_type:
                # Future: Change encodestring to encodebytes when python3 only
                node.set('xlink:href', 'data:{};base64,{}'.format(
                    file_type, base64.encodebytes(handle.read()).decode('ascii')))
                node.pop('sodipodi:absref')
            else:
                inkex.errormsg("%s is not of type image/png, image/jpeg, "
                               "image/bmp, image/gif, image/tiff, or image/x-icon" % path)


    # REFACTOR
    # This method does not really save the image to the epub anymore, it just sets the correct
    # href value to point to the resource folder.
    # This will probably be changed back to its original purpose when I have time to refactor
    # the code a bit.
    def save_image_to_epub(self, image, book):
        resource_folder_path = os.path.join(self.root_folder, self.resources_folder)

        xlink = image.get('xlink:href')

        if xlink is None or xlink == '':
            # No xlink found
            inkex.utils.debug('No valid xlink. Found: %s' % xlink)
            return

        # Let's check if the xlink contains a data uri
        if xlink[:5] == 'data:':
            # No need, data already embedded
            return

        url = urllib.parse.urlparse(xlink)
        href = urllib.request.url2pathname(str(url.path))

        # Primary location always the filename itself.
        path = self.absolute_href(href or '')

        # Backup directory where we can find the image
        if not os.path.isfile(path):
            path = image.get('sodipodi:absref', path)

        if not os.path.isfile(path):
            inkex.errormsg('File not found "{}". Unable to save and add image.'.format(path))
            return

        with open(path, "rb") as handle:
            file_type = self.get_image_type(path, handle.read(10))

            # Is the image in the resources folder?
            if(path.find(resource_folder_path) >= 0):
                file_name = self.get_relative_resource_path(path)
            else:
                inkex.utils.debug("save_image_to_epub: image '"+ path +"' is not in resource folder, skipping it.")
                handle.close()
                handle = None
                return

            handle.seek(0)

            if file_type:
                # We do not need to do this anymore since I have decided that all resources, including images
                # must be put in the resources folder and all those have already been added to the EPUB package.
                # item = inx_epub.InxEpubItem(uid=image.get('id'), file_name=file_name, media_type=file_type, content=handle.read(), create=False)
                # self.book.add_item(item)

                # Rewrite the urls
                image.set('sodipodi:absref', file_name)
                image.set('xlink:href', file_name)

            else:
                inkex.errormsg("%s is not of type image/png, image/jpeg, "
                               "image/bmp, image/gif, image/tiff, or image/x-icon" % path)

    def get_image_type(self, path, header):
        # Basic magic header checker, returns mime type
        for head, mime in (
                (b'\x89PNG', 'image/png'),
                (b'\xff\xd8', 'image/jpeg'),
                (b'BM', 'image/bmp'),
                (b'GIF87a', 'image/gif'),
                (b'GIF89a', 'image/gif'),
                (b'MM\x00\x2a', 'image/tiff'),
                (b'II\x2a\x00', 'image/tiff'),
        ):
            if header.startswith(head):
                return mime

        # ico files lack any magic... therefore we check the filename instead
        for ext, mime in (
                # official IANA registered MIME is 'image/vnd.microsoft.icon' tho
                ('.ico', 'image/x-icon'),
                ('.svg', 'image/svg+xml'),
        ):
            if path.endswith(ext):
                return mime
        return None

    def save_images_to_epub(self, element, book):
        images = element.xpath('//svg:image')

        # make sure that the image hrefs are relative to the "project root"
        for image in images:
            self.save_image_to_epub(image, book)

    # TODO: Separate out some of the code into functions to increase readability

    # def process_fonts(self):
    #     pass
    #
    # def create_epub(self, title):
    #     pass
    #
    # def add_epub_manifest_item(self, item):
    #     pass
    #
    # def add_epub_metadata_item(self, item):
    #     pass
    #
    # def add_epub_spine_item(self, id, item):
    #     pass
    #
    # def add_epub_nav_item(self, item):
    #     pass
    #
    # def add_cover_content_document(self, doc):
    #     pass
    #
    # def add_content_document(self, doc):
    #     pass
    #
    # def fragment_to_svg_doc(self, fragment):
    #     pass
    #
    # def get_document_layers(self):
    #     pass
    #
    # def render_css(self, source):
    #     pass


# Create effect instance and apply it.
effect = ExportToEpub()

effect.run(output=False)

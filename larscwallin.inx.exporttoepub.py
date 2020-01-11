#!/usr/bin/env python

import base64
import sys
import urllib.parse
import urllib.request
import os
import glob
from pathlib import Path

from lxml import etree, html
from builtins import str

sys.path.append('./')
sys.path.append('./inkex')
sys.path.append('/usr/share/inkscape/extensions')
sys.path.append('./ebooklib')
sys.path.append('./scour')

import re
import inkex
import scour.scour
from ebooklib import epub

class ExportToEpub(inkex.Effect):
    svg_src_template = """<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="100%" height="100%" viewBox="0 0 {{element.width}} {{element.height}}" xml:space="preserve" preserveAspectRatio="xMinYMin">
    <style id="font-declarations">
        {{font-families}}
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
      src: url({{font.url}});
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
                                     type=inkex.Boolean, dest='bottom_layer_as_cover', default=True,
                                     help='Use bottom layer as cover image?')

        self.arg_parser.add_argument('--wrap_svg_in_html', action='store',
                                     type=inkex.Boolean, dest='wrap_svg_in_html', default=False,
                                     help='Save documents as HTML instead of SVG?')

    def effect(self):
        self.publication_title = "Publication Title"
        self.destination_path = self.options.where
        self.root_folder = self.options.root_folder
        self.filename = self.options.filename
        self.resources_folder = self.options.resources_folder
        self.resource_items = []
        self.bottom_layer_as_cover = self.options.bottom_layer_as_cover
        self.wrap_svg_in_html = self.options.wrap_svg_in_html
        self.svg_doc = self.document.xpath('//svg:svg', namespaces=inkex.NSS)[0]
        self.svg_width = int(round(self.svg.unittouu(self.svg_doc.get('width'))))
        self.svg_height = int(round(self.svg.unittouu(self.svg_doc.get('height'))))
        self.visible_layers = self.document.xpath('//svg:svg/svg:g[not(contains(@style,"display:none"))]',
                                                  namespaces=inkex.NSS)
        self.book = epub.EpubBook()

        if self.visible_layers.__len__() > 0:
            selected_layers = []
            content_documents = []
            defs = self.document.xpath('//svg:svg/svg:defs', namespaces=inkex.NSS)
            defs_string = ''
            scripts = self.document.xpath('//svg:svg/svg:script', namespaces=inkex.NSS)
            scripts_string = ''
            text_elements = self.document.xpath('//svg:text', namespaces=inkex.NSS)
            font_declarations = {}
            font_families_string = ''

            resource_folder_path = os.path.join(self.root_folder, self.resources_folder)
            self.add_resources(resource_folder_path)

            for text in text_elements:
                style = inkex.Style(text.get('style'))

                if style['font-family']:
                    font = style['font-family']
                    if font not in font_declarations:
                        font_declarations[font] = font

            if len(scripts) > 0:
                for script in scripts:
                    xlink = script.get('xlink:href')

                    if xlink:
                        script_source = self.read_file(xlink)
                        if script_source is not None:
                            script_name = os.path.basename(xlink)
                            script_item = epub.EpubItem(file_name=('scripts/' + script_name),
                                                        media_type='text/javascript', content=script_source)
                            self.book.add_item(script_item)

                            scripts_string += str(
                                '<script src="' + ('scripts/' + script_name) + '"></script>')
                    else:
                        script_source = script.text
                        if script_source:
                            scripts_string += str(
                                '<script id="' + script.get('id') + '">' + script_source + '</script>')

            else:
                scripts_string = '<script />'

            if len(defs) > 0:
                for element in defs:
                    defs_string += str(etree.tostring(element, method='html', pretty_print=False), 'utf-8')
            else:
                defs_string = '<defs/>'

            metadata = self.document.xpath('//svg:svg/svg:metadata/rdf:RDF/cc:Work', namespaces=inkex.NSS)
            metadata_items = {
                'title': '',
                'format': '',
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
                    self.remove_namespace(element, 'http://purl.org/dc/elements/1.1/')
                    metadata_items[element.tag] = element.text
            else:
                pass

            if metadata_items['title'] != '':
                self.publication_title = metadata_items['title']

            # set metadata
            for term, val in metadata_items.items():
                if val != '':
                    self.book.add_metadata('DC', term, val)

            self.book.add_metadata(None, 'meta', 'pre-paginated', {'property': 'rendition:layout'})
            self.book.add_metadata(None, 'meta', 'auto', {'property': 'rendition:orientation'})

            for element in self.visible_layers:

                # Save all images to epub package
                self.save_images_to_epub(element, self.book)

                element_label = str(element.get(inkex.utils.addNS('label', 'inkscape'), ''))
                element_id = element.get('id')

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
                    tpl_result = str.replace(tpl_result, '{{element.width}}', str(self.svg_width))
                    tpl_result = str.replace(tpl_result, '{{element.height}}', str(self.svg_height))
                    tpl_result = str.replace(tpl_result, '{{element.source}}', str(element_source, 'utf-8'))

                    for font in font_declarations:
                        font_tpl_result = ''

                        font_family = str.replace(font, ' ', '+')
                        font_family = str.replace(font_family, "'", '')
                        resource_path = os.path.join(self.root_folder, self.resources_folder)
                        font_file_name = self.find_file_name_fuzzy(font_family, resource_path)

                        if font_file_name is not None:
                            font_path = self.resources_folder + '/' + font_file_name
                            font_tpl_result = str.replace(self.font_face_template, '{{font.family}}', font_family)
                            font_tpl_result = str.replace(font_tpl_result, '{{font.url}}', font_path)

                            font_families_string = font_families_string + font_tpl_result
                        else:
                            inkex.utils.debug('Could not find matching font file ' + font_family)

                    if self.wrap_svg_in_html:
                        tpl_result = str.replace(tpl_result, 'font-families', font_families_string)
                    # else:
                    #     Move and uncomment to add custom font support to spine level svg export
                    #     content_doc.getroot().addprevious(etree.ProcessingInstruction('xml-stylesheet', 'href="https://fonts.googleapis.com/css?family=' + alias + '"'))

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


            # self.book.add_item(epub.EpubItem(file_name=font_item.filename, media_type='application/x-font-truetype'))

            for node in selected_layers:
                # Cache these in local vars
                content = node['source']
                id = node['id']
                label = node['label'] or node['id']

                if content != '':

                    if self.wrap_svg_in_html:
                        doc = epub.EpubHtml(uid=label, file_name=label + '.html', media_type="text/html",
                                          content=content, width=self.svg_width, height=self.svg_height)

                        content_documents.append(doc)

                    else:
                        content_documents.append(
                            epub.EpubSvg(uid=label, file_name=label + '.svg', media_type="image/svg+xml",
                                         content=content))
                else:
                    pass

            if self.bottom_layer_as_cover:
                cover = content_documents[0]
                cover.content = re.subn(r'<(script).*?</\1>(?s)', '', cover.content.decode('utf-8'))[0]
                cover.properties.append('cover-image')
                self.book.add_metadata(None, 'meta', '', epub.OrderedDict([('name', 'cover'), ('content', cover.id)]))

            else:
                cover_content = '<html><head><title>' + str(self.publication_title) + '</title></head><body><h1>' + str(
                    self.publication_title) + '</h1></body></html>'
                self.book.set_cover('cover.html', cover_content, create_page=False)

            for doc in content_documents:

                if len(scripts) > 0 and 'cover-image' not in doc.properties:
                    doc.properties.append('scripted')

                # add manifest item
                self.book.add_item(doc)

                # add spine item
                self.book.spine.append(doc)

            # TODO: Actually add the documents to the NAV
            self.book.add_item(epub.EpubNav())

            epub.write_epub((self.destination_path + '/' + self.filename), self.book, {})

            inkex.utils.debug('Saved EPUB file to ' + (self.destination_path + '/' + self.filename))

        else:
            inkex.utils.debug('No SVG elements or layers to export')

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
                        rel_path = str.split(folder, self.root_folder)[1]
                        rel_path = rel_path.lstrip('/\\')
                        item = epub.EpubItem(file_name=os.path.join(rel_path, resource), content=resource_content)
                        self.book.add_item(item)

                        #resource_type = guess_type(resource_path)
                        #
                        # self.resource_items.append(
                        #     {
                        #         'name': resource,
                        #         'type': resource_type,
                        #         'path': resource_path,
                        #         'content': resource_content
                        #     }
                        # )
                    else:
                        inkex.utils.debug('"' + resource + '" is empty')
        else:
            inkex.utils.debug('"' + folder + '" is not a folder')

    def gettag_name(self, node, ns='sodipodi'):
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

    def find_file_name_fuzzy(self, name, dir):
        folder = Path(dir)
        files = folder.rglob('*' + name + '*.*')
        for file in files:
            inkex.utils.debug('found file ' + str(file))
            return str(os.path.basename(file))

        return None


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

    def save_image_to_epub(self, image, book):
        """Embed the data of the selected Image Tag element"""
        inkex.utils.debug('node %s' % image)
        xlink = image.get('xlink:href')

        if xlink is None or xlink == '':
            # No valid xlink
            inkex.utils.debug('No valid xlink. Found: %s' % xlink)
            return

        if xlink and xlink is not None and xlink[:5] == 'data:':
            # No need, data alread embedded
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
            file_name = os.path.basename(path)
            handle.seek(0)

            if file_type:
                item = epub.EpubItem(uid=image.get('id'), file_name=file_name, media_type=file_type,
                                     content=handle.read())
                self.book.add_item(item)
                image.set('sodipodi:absref', file_name)
                image.set('xlink:href', file_name)

            else:
                inkex.errormsg("%s is not of type image/png, image/jpeg, "
                               "image/bmp, image/gif, image/tiff, or image/x-icon" % path)

    def get_image_type(self, path, header):
        """Basic magic header checker, returns mime type"""
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

        for image in images:
            self.save_image_to_epub(image, book)

    def process_fonts(self):
        # Find and iterate over all font-family references
        # For each font-family, create processing instruction:
        #
        # <?xml-stylesheet type="text/css" href="https://fonts.googleapis.com/css?family=Rammetto+One"?>
        #
        # self.document.getroot().addprevious(etree.ProcessingInstruction('xml-stylesheet', 'type="text/css" href="https://fonts.googleapis.com/css?family=Rammetto+One"'))
        pass

    def create_epub(self, title):
        pass

    def add_epub_manifest_item(self, item):
        pass

    def add_epub_metadata_item(self, item):
        pass

    def add_epub_spine_item(self, id, item):
        pass

    def add_epub_nav_item(self, item):
        pass

    def add_cover_content_document(self, doc):
        pass

    def add_content_document(self, doc):
        pass

    def fragment_to_svg_doc(self, fragment):
        pass

    def get_document_layers(self):
        pass

    def render_css(self, source):
        pass

    # def downloadGoogleFont(self, font_desc, path):

    # formats =  {"truetype": "ttf"} # sorted(fontdl.fontfmt_user_agent.keys())
    # inkex.utils.debug(font_desc)
    # font_args = fontdl.parse_font_arg(font_desc)
    # fetched = fontdl.fetch_fonts(frozenset(formats), None, [font_args])
    # fontdl.connection_pool.close_all()
    # return fetched


# Create effect instance and apply it.
effect = ExportToEpub()

effect.run(output=False)

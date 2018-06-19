# coding: utf-8
# !/usr/bin/env python

# Copyright 08-May-2016, 14:51:07
#
# Author    : Dulip Withanage , University of Heidelberg

import copy
import collections
import io
from itertools import chain
import json
import logging
import os
from sets import Set
import sys
import time
import uuid
import zipfile
import re

try:
    from citation_parser import CitationParser
except ImportError:
    print('pip install citation-parser')
    print('pip install http://www.antlr3.org/download/Python/antlr_python_runtime-3.1.3.tar.gz')

try:
    from lxml import etree
    from lxml import objectify
except ImportError:
    print("Failed to import ElementTree, plase install")

LOG_FILE = 'jatsPostProcess.log'
numeral_map = tuple(zip(
    (1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1),
    ('M', 'CM', 'D', 'CD', 'C', 'XC', 'L', 'XL', 'X', 'IX', 'V', 'IV', 'I')
))


# logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG)


class PostProcess:
    '''
     command line tool to clean, modify, delete, merge jats files
    '''

    def __init__(self, cf):
        try:
            with open(cf) as json_data_file:
                self.config = json.load(json_data_file)
        except:
            print
            'Please define', cf
            sys.exit(1)

        self.JATS_XML_HEADER = '<article xmlns:xlink="http://www.w3.org/1999/xlink">'
        self.doc_type = '<!DOCTYPE article PUBLIC "-//NLM//DTD Journal Publishing DTD v3.0 20080202//EN" "http://dtd.nlm.nih.gov/publishing/3.0/journalpublishing3.dtd">'
        self.xml = '<?xml version="1.0" encoding="UTF-8"?>'

    def print_unreferenced_figs(self, tr, f):
        a = self.get_fig_refs_body(tr)
        b = self.get_fig_ids_body(tr)
        if len(a - b) > 0:
            print
            f, a - b
        return tr

    def apply_transformations(self, tr, context, f, chapter, order, count):
        ''' main method to apply transformations'''
        cfg = self.config["createFull"][context]

        # tr = self.remove_not_used_in_back(tr, "ref-list/ref")
        tr = self.remove_not_used_in_back(tr, "fn-group/fn")
        tr = self.set_uuid_figs(tr)
        if "enumeration" in cfg.keys():
            if cfg["enumeration"] == 1:
                if "chapter-begin-reset" in cfg.keys():
                    if cfg["chapter-begin-reset"] == 1:
                        count = 1
                tr, count = self.set_enumeration(
                    tr, "xref", "ref-type", "fn", context, f, chapter, order, count)
        tr = self.remove_name_duplicates_speech(tr)
        tr = self.set_numbering(tr, ['speech', 'disp-quote', "abstract"])
        tr = self.get_unreferenced_footnotes(tr)
        tr = self.set_uuid_fns(tr, 'fn')

        tr = self.print_unreferenced_figs(tr, f)

        tr = self.merge_repeating_neighbours(tr, "disp-quote")
        if "references" in cfg.keys():

            if "duplicates" in cfg["references"].keys():
                for i in cfg["references"]["duplicates"]:
                    tr = self.remove_duplicate_refs(tr, i)

        if "citations-to-references" in cfg.keys():
            if cfg["citations-to-references"] == 1:
                tr = self.citations_to_references(tr)
        if "references-to-citations" in cfg.keys():
            if cfg["references-to-citations"] == 1:
                tr = self.references_to_citations(tr)

        if "create-automated-references" in cfg.keys():
            if cfg["create-automated-references"] == 1:
                tr = self.create_automated_references(tr)

        tr = self.remove_duplicate_http_links(tr)

        return tr, count

    def references_to_citations(self, tr):
        """ Converts References Block to real citations

        Returns
         -------
         tr : elementtree

        """

        root = tr.getroot()
        titles = root.findall('.//body/sec/sec/sec/title')
        rl = root.find('.//ref-list')
        # cp = CitationParser()

        for t in titles:
            if t.text == 'References':
                children = t.getparent().getchildren()
                for child in children:
                    if child.tag == 'p':
                        sc = etree.Element('ref')
                        cit = copy.deepcopy(child)
                        cit.tag = 'mixed-citation'
                        if rl is not None:
                            sc.append(cit)
                            rl.append(sc)
        return tr

    def create_automated_references(self, tr):
        # front
        xrefs = tr.findall('.//xref')
        # cp = CitationParser()

        # back

        rl = tr.findall('.//ref')
        for xref in xrefs:
            if xref.attrib['ref-type'] == 'bibr':
                if xref.text is not None:
                    t = xref.text
                    a_y = t.split(' ')
                    if len(a_y) > 1:
                        work = a_y[0]
                        year = a_y[1].replace(',', '')
                        for ref in rl:
                            if ref[0].text:
                                try:
                                    cit = ref[0].text.split(',')
                                    cit_year = cit[1].split('.')[1]
                                    if int(cit_year) == int(year) and str(cit[0]) == str(work):
                                        idx = 'refIDAuto' + work + '' + year
                                        xref.set('rid', idx)
                                        ref.set('id', idx)
                                except:
                                    pass
        i, j = 0, 0
        print
        '\n| RefID (rid) | id |'
        print
        '| --- |  --- |'
        for xref in xrefs:
            if xref.attrib['ref-type'] == 'bibr':
                if xref.attrib['rid'].startswith('ID'):
                    print
                    '| {} | {} | '.format(xref.attrib['rid'], xref.attrib['id'])
                    i += 1
                else:
                    j += 1

        print
        '\n'
        print
        i, 'nicht automatisiert'
        print
        j, ' automatisiert'

        return tr

    def citations_to_references(self, tr):
        """ Removes  mixed-citation block, adds as a <sec> Section element

        Returns
         -------
         tr : elementtree

        """

        t = tr.getroot()
        bd = t.find('.//body/sec')
        sc = etree.Element('sec')
        ttl = etree.Element('title')
        ttl.text = 'References'
        sc.append(ttl)
        mc = t.findall('.//mixed-citation')
        if len(mc) > 0:
            for r in mc:
                cit = copy.deepcopy(r)
                cit.tag = 'p'
                sc.append(cit)
        bd.append(sc)
        '''
        # delete references 
                rlst = t.find('.//ref-list')
                rlst.getparent().remove(rlst)
                bck = t.find('.//back')
                bck.append(etree.Element('ref-list'))
        '''

        return tr

    def contains(self, a, v):
        ''' help method to compare references '''
        (c1, c2, c3, c4) = v
        if c1 and c2:
            for (v1, v2, v3, v4) in a:
                if v1 == c1 and v2 == c2 and v3 == c3 and v4 == c4:
                    return True
        return False

    def convert_int_to_roman(self, i):
        result = []
        for integer, numeral in numeral_map:
            count = i // integer
            result.append(numeral * count)
            i -= integer * count
        return ''.join(result)

    def convert_roman_to_int(self, n):
        i = result = 0
        for integer, numeral in numeral_map:
            while n[i:i + len(numeral)] == numeral:
                result += integer
                i += len(numeral)
        return result

    def create_files(self, context):
        ''' main method : creates zip, merges and transforms xml files '''
        cfb = self.config['createFull'][context]

        # self.create_zip(cfb["dir"], cfb["files"])

        fullfile = cfb["fullfile"].keys()[0]

        header_text, back_fns, body_secs, back_refs, elem_secs, elem_fns = self.modify_files(
            cfb["dir"], cfb["files"], context)

        self.create_merged_file(
            fullfile,
            body_secs,
            back_fns,
            back_refs,
            header_text,
            cfb,
            context)

        self.create_footnote_file(
            cfb,
            back_fns,
            header_text,
            body_secs,
            elem_secs,
            elem_fns)

        return None

    def create_footnote_file(
            self, cfb, back_fns, header_text, body_secs, elem_secs, elem_fns):
        # print len(elem_secs) , len(elem_fns)
        if "footnotes_file" in cfb.keys():
            if cfb["footnotes_file"].keys():
                footnotes_file = cfb["footnotes_file"].keys()[0]
                fpfn = os.path.join(cfb["dir"], footnotes_file)
                fns_p, fnn, range_count = [], 1, 1
                ###
                if len(elem_secs) != len(elem_fns):
                    logging.info(
                        "each document must have  a section and a footnote")
                    # sys.exit(1)

                for i in range(0, len(elem_secs)):
                    if len(elem_fns[i]) > 0:
                        fns_p.append('<sec>')
                        fns_p.append(
                            etree.tostring(
                                elem_secs[i].find('title')))
                        for j in list(elem_fns[i]):
                            number, range_count = self.set_roman_numbers(
                                fnn, range_count, cfb["footnotes_file"].values()[0])
                            b = '<bold>' + str(number) + ' </bold>'
                            s = etree.tostring(
                                j.getchildren()[0]).replace(
                                '>', '>' + b, 1)
                            fns_p.append(s)
                            fnn = fnn + 1
                        fns_p.append('</sec>')
                ###
                # for i in back_fns:
                #  number, range_count = self.set_roman_numbers(fnn,range_count,cfb["footnotes_file"].values()[0])
                #  k = etree.XML('<p><bold>' + str(number) +' </bold>   ' +self.get_stringified_children(etree.fromstring(i).getchildren()[0]) + '</p>')
                #  fns_p.append(etree.tostring(k))

                out_fn = out = "%s%s%%s%s<body><sec><title>%s</title>%s</sec></body><back></back></article>" % (
                    self.xml, self.doc_type, self.JATS_XML_HEADER, header_text, 'Anmerkungen', ''.join(fns_p))
                f = open(fpfn, 'w')
                f.write(out_fn)
                f.close()
                logging.info('footnotes\t' + str(footnotes_file))

    def create_merged_file(self, fullfile, body_secs,
                           back_fns, back_refs, header_text, cfb, context):

        fp = os.path.join(cfb["dir"], fullfile)
        body_text = ''.join(body_secs)
        fns = ''.join(back_fns)
        refs = ''.join(back_refs)

        out = "%s%s%s%s<body>%s</body><back><fn-group>%s</fn-group><ref-list>%s</ref-list></back></article>" % (
            self.xml, self.doc_type, self.JATS_XML_HEADER, header_text, body_text, fns, refs)
        f = open(fp, 'w')
        f.write(out)

        f.close()
        count = 1
        tr = self.apply_transformations(
            self.get_etree(fp), context, fullfile, False, 0, count)
        self.create_output(tr, fp)


    def create_output(self, tree, f):
        ''' write element tree to f '''
        print
        100 * '-'

        if isinstance(tree, etree._ElementTree):
            try:
                etree.cleanup_namespaces(tree.getroot())
                import xml.etree.cElementTree as ElementTree

                tree.write(
                    f,
                    pretty_print=True,
                    xml_declaration=True,
                    encoding='UTF-8')
                logging.debug('File written {0}'.format(f))


            except:
                logging.info(self.config['errors']['FILE_NOT_WRITTEN'])

    def create_refs_csv(self, dr, infile, outfile, types):
        ''' write a csv f from the references '''
        f = os.path.join(dr, infile)
        tree = self.get_etree(f)
        elem = tree.find('./back/ref-list')
        out = ''
        for e in elem:
            for t in types:
                if e.find('.//' + t) is not None:
                    out += e.find('.//' + t).text + ','
                out += '\n'
        tf = open(outfile, "w")
        tf.write(unicode(out).encode("utf-8"))
        tf.close()

    def create_zip(self, dr, files):
        ''' create a zip file from a set of files and a directory path '''
        try:
            z = zipfile.ZipFile(os.path.join(dr, ''.join(
                [self.config["zip"]["name-prefix"], str(time.time()), '.zip'])), "w")
            for f in files:
                z.write(os.path.join(dr, f),
                        compress_type=zipfile.ZIP_DEFLATED)
        except:
            pass

    def get_etree(self, infile):
        ''' reads a file and get the element tree '''
        try:
            tree = etree.parse(infile)
        except:
            print
            self.config['errors']['FILE_NOT_FOUND']
            sys.exit(2)
        return tree

    def get_footnotes_back(self, tree):
        '''returns footnotes in back '''
        back_fns = Set()
        for back in tree.getroot().findall(".//back/fn-group"):
            for fn in back.findall(".fn"):
                if fn.keys():
                    back_fns.add(fn.attrib['id'])
        return back_fns

    def get_fig_refs_body(self, tree):
        body_figs = Set()
        for body in tree.getroot().findall(".//body"):
            for fn in body.findall(".//xref[@ref-type='fig']"):
                if fn.keys():
                    body_figs.add(fn.attrib['rid'])
        return body_figs

    def get_fig_ids_body(self, tree):
        back_refs = Set()
        for back in tree.getroot().findall(".//fig-group"):
            for ref in back.findall(".fig"):
                if ref.keys():
                    back_refs.add(ref.attrib['id'])
        return back_refs

    def get_footnotes_body(self, tree):
        '''returns footnotes in body '''
        body_fns = Set()
        for body in tree.getroot().findall(".//body"):
            for fn in body.findall(".//xref[@ref-type='fn']"):
                if fn.keys():
                    body_fns.add(fn.attrib['rid'])
        return body_fns

    def get_ref_ids_back(self, tree):
        '''returns references in back '''
        back_refs = Set()
        for back in tree.getroot().findall(".//back/ref-list"):
            for ref in back.findall(".ref"):
                if ref.keys():
                    back_refs.add(ref.attrib['id'])
        return back_refs

    def get_ref_ids_body(self, tree):
        '''returns references in body '''
        body_refs = Set()
        for body in tree.getroot().findall(".//body"):
            for ref in body.findall(".//xref[@ref-type='bibr']"):
                if ref.keys():
                    body_refs.add(ref.attrib['rid'])
        return body_refs

    def get_stringified_children(self, node):

        parts = ([node.text] + list(chain(*([c.text, etree.tostring(c), c.tail]
                                            for c in node.getchildren()))) + [node.tail])
        return ''.join(filter(None, parts)).encode('utf-8').strip()

    def get_refs_mixed_back(self, tree):
        '''returns mixed citations in back '''
        back_refs = Set()
        for back in tree.getroot().findall(".//back/ref-list/ref"):
            for ref in back.findall(".//mixed-citation"):
                logging.info(
                    "Mixed reference found", self.stringify(back))
        return back_refs

    def get_unreferenced_footnotes(self, tr):
        ''' returns a list of footnotes, which are not in body '''
        body_fns = self.get_footnotes_body(tr)
        back_fns = self.get_footnotes_back(tr)
        for i in back_fns:
            if i in body_fns:
                pass
            else:
                logging.info("Footnote " + i + " is not used")

        return tr

    def merge_repeating_neighbours(self, tr, etype):
        root = tr.getroot()
        for i in root.findall('.//' + etype):
            if i.tag == etype:
                if i.getparent().getprevious() is not None:
                    if i.getparent().getprevious().getchildren():
                        if i.getparent().getprevious().getchildren()[
                            0].tag == etype:
                            i.getparent().getprevious().getchildren()[
                                0].append(copy.deepcopy(i.getchildren()[0]))
                            i.getparent().getparent().remove(i.getparent())
        return tr

    def modify_files(self, dr, files, context):
        '''  merge  a set of xml files in a directory'''
        back_fns, body_secs, back_refs = [], [], []
        elem_secs, elem_fns = [], []
        header = False
        header_text = ''
        order = 0
        count = 1
        for f in files:
            f = f.keys()[0]
            logging.info("Parsing file\t" + f)
            print(os.path.join(dr, f))
            tr = etree.parse(os.path.join(dr, f))
            tr, count = self.apply_transformations(
                tr, context, f, True, order, count)
            self.create_output(tr, os.path.join(dr, f))
            root = tr.getroot()
            if not header:
                for header_text in root.findall(".//front"):
                    header_text = ''.join(self.stringify(header_text))
                    header = True
            for sec in root.findall(".//body/sec"):
                body_secs.append(self.stringify(sec))
            for fn in root.findall(".//back/fn-group/fn"):
                back_fns.append(self.stringify(fn))

            for ref in root.findall(".//back/ref-list/ref"):
                back_refs.append(self.stringify(ref))

            for sec in root.findall(".//body/sec"):
                elem_secs.append(sec)
            for fn in root.findall(".//back/fn-group"):
                elem_fns.append(fn)

            order += 1

        return header_text, back_fns, body_secs, back_refs, elem_secs, elem_fns

    def stringify(self, tree):
        return etree.tostring(tree, pretty_print=True)

    def remove_all_elements_of_type(self, tree, names):
        ''' removes all the elements of a certain type in a element tree '''
        for name in names:
            for elem in tree.getroot().findall('.//' + name):
                elem.getparent().remove(elem)
        return tree

    def remove_comments(self, tree):
        ''' removes all the comments  in a element tree '''
        comments = tree.xpath('//comment()')
        for c in comments:
            p = c.getparent()
            p.remove(c)
        return tree

    def remove_duplicate_http_links(self, tr):
        # HYPERLINK          "http://upload.wikimedia.org/wikipedia/commons/4/4b/%C3%9Altima_Cena_-Da_Vinci_5.jpg"
        # <ext-link xlink:href="http://upload.wikimedia.org/wikipedia/commons/4/4b/%C3%9Altima_Cena_-Da_Vinci_5.jpg"
        # ext-link-type="uri" xlink:type="simple">http://upload.wikimedia.org/wikipedia/commons/4/4b/%C3%9Altima_Cena_-Da_Vinci_5.jpg</ext-link>
        tr_str = etree.tostring(tr, encoding='utf8', method='xml').replace('\n', ' ').replace('\r', '')
        tr_str = re.sub(
            'HYPERLINK(\W)*(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F])))(\S)*', '',
            tr_str)
        root = etree.fromstring(tr_str)
        tr = etree.ElementTree(root)
        return tr

    def remove_duplicate_refs(self, tr, tag_list):
        ''' removes duplicate references'''
        ref_list = tr.find('./back/ref-list')
        if ref_list:
            data = []
            drf = {}
            for e in ref_list:

                vl = []
                for tag in tag_list:
                    vl.append(e.findtext(".//" + tag))
                vl.append(e)
                data.append(tuple(vl))

            data.sort()

            ref_list[:] = [item[-1] for item in data]
            prev = ('', '', '', '')
            last_id = 0

            for j, v in enumerate(data):
                if v[0] is not None and v[1] is not None and v[2] is not None:
                    if prev[0] == v[0] and prev[1] == v[1] and prev[2] == v[2]:
                        drf[last_id] = v[len(v) - 1].attrib['id']
                    else:
                        prev = v
                        last_id = v[len(v) - 1].attrib['id']
            # replace refs
            i = 0
            for key in drf:
                for xref in tr.findall(
                        './/xref[@rid="' + drf[key] + '"]'):
                    xref.set('rid', key)
                for ref in tr.findall('.//ref[@id="' + drf[key] + '"]'):
                    i += 1
                    ref.getparent().remove(ref)
        return tr

    def remove_name_duplicates_speech(self, tr):
        ''' removes name duplication  in  speech tag '''
        for elem in tr.getroot().findall('.//speech/p'):
            for l in list(elem):
                if l is not None:
                    elem.text = ""
        return tr

    def remove_not_used_in_back(self, tr, tag):
        ''' removes  footnotes, references, which are not linked. '''
        body_refs = self.get_ref_ids_body(tr)
        back_refs = self.get_ref_ids_back(tr)

        for i in back_refs:
            if i in body_refs:
                pass
            else:
                elm = ''.join(['.//back/', tag, '/[@id="', str(i), '"]'])
                elems = tr.getroot().findall(elm)

                for e in elems:
                    self.remove_element(e)
        # TODO remove without ids
        for e in tr.getroot().xpath('.//back/' + tag + '[not(@id)]'):
            self.remove_element(e)
        return tr

    def remove_element(self, e):
        if e.getparent() is not None:
            e.getparent().remove(e)

    def remove_table_references(self, tree, name, attr, value):
        searchTag = './/' + name + '[@' + attr + '="' + value + '"]'
        try:
            with open(self.TABLESTYLEFILE, 'r') as file:
                xslt = file.read()
        except:
            logging.error(self.config['errors']['FILE_NOT_FOUND'])
            sys.exit(2)
        xslt_doc = etree.parse(io.BytesIO(xslt))
        transform = etree.XSLT(xslt_doc)
        return transform(tree)

    def set_enumeration(self,tr,name,attr,value,context,f,chapter,order,count):
        ''' set the count id for an attribute in a tag type '''
        searchTag = './/' + name + '[@' + attr + '="' + value + '"]'
        elems = tr.getroot().findall(searchTag)
        cfg = self.config["createFull"][context]
        cf = cfg["files"][order][f] if chapter else cfg['fullfile'][f]

        range_count = 1
        for elem in elems:
            elem.text, range_count = self.set_roman_numbers(
                count, range_count, cf)
            count += 1
        return tr, count

    def set_numbering(self, tree, tags):
        ''' tags auto-numbering'''
        for tag in tags:
            sid = 1
            for i in tree.findall('.//' + tag):
                i.set('id', tag.replace('-', '') + str(sid))
                sid += 1
        return tree

    def set_roman_numbers(self, count, range_count, cf):
        val = str(count)
        if 'numbering' in cf.keys():
            if cf['numbering'] == 'roman':
                if 'range' in cf.keys():
                    j = cf['range'][0]
                    if count >= int(j[0]) and count <= int(j[1]):
                        val = self.convert_int_to_roman(range_count).lower()
                        range_count += 1
                    else:
                        val = str(count - range_count + 1)
                else:
                    val = self.convert_int_to_roman(count).lower()

        return val, range_count

    def set_uuid_fns(self, tr, s):

        for fn in tr.getroot().findall('.//fn'):
            uid = ''.join(['fn_', str(uuid.uuid4())[0:8]])
            fn_id = fn.attrib['id']
            fn.set('id', uid)
            for xref in tr.getroot().findall('.//xref/[@rid="' + fn_id + '"][@ref-type="fn"]'):
                xref.set('rid', uid)

        return tr

    def set_uuid_figs(self, tr):
        for fig in tr.getroot().findall('.//fig'):
            uid = ''.join(['fig_', str(uuid.uuid4())[0:8]])
            fig_id = fig.attrib['id']
            fig.set('id', uid)
            for xref in tr.getroot().findall('.//xref/[@rid="' + fig_id + '"][@ref-type="fig"]'):
                xref.set('rid', uid)

        return tr

    def sort_references(self, tr, parent, tag_list):
        ''' sort all the references  '''
        elem = tr.find('./back/ref-list')
        data = []
        for e in elem:
            vl = []
            for tag in tag_list:
                vl.append(e.findtext(".//" + tag))
            vl.append(e)
            data.append(tuple(vl))
        data.sort()
        elem[:] = [item[-1] for item in data]

        return tr


def main():
    if len(sys.argv) >= 2:
        p = PostProcess(sys.argv[1])
        context = "example"
        p.create_files(context)
        # with open(LOG_FILE) as f:
        #    print f.read()
        # os.remove(LOG_FILE)
    else:
        print
        'json file not defined, please define the path'


if __name__ == "__main__":
    main()

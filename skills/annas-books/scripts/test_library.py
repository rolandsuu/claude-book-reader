import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import library

def fixture(path, body=None, encrypted=False):
    body = body or '<h1 id="one">Chapter One</h1><p>First <em>paragraph</em>.</p><h1><a id="two"></a>Chapter Two</h1><pre>if x:\n    print(x)</pre><p>Second paragraph.</p><p><img src="image.png" alt="A diagram"/></p>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('mimetype','application/epub+zip')
        z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        z.writestr('OPS/book.opf','<package><metadata><title>Fixture</title><creator>Author</creator></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="body"/></spine></package>')
        z.writestr('OPS/nav.xhtml','<html><body><nav epub:type="toc"><ol><li><a href="body.xhtml#one">Chapter One</a></li><li><a href="body.xhtml#two">Chapter Two</a></li></ol></nav></body></html>')
        z.writestr('OPS/body.xhtml','<html><head><title>Not body</title><style>hidden</style></head><body>'+body+'</body></html>')
        if encrypted:
            z.writestr('META-INF/encryption.xml','<encryption><EncryptionMethod Algorithm="DRM"/></encryption>')

class LibraryTests(unittest.TestCase):
    def test_same_document_anchors_and_code(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'book.epub';fixture(source)
            out=Path(temp)/'out';plan=library.prepare(source,out)
            self.assertEqual(plan['status'],'indexed_locally')
            self.assertEqual(json.loads((out/'upload-plan.json').read_text())['status'],'indexed_locally')
            self.assertEqual(library.sha(source),library.sha(out/'source.epub'))
            self.assertEqual(plan['chapter_count'],3)  # explicit front matter plus two TOC targets
            second=library.lookup(out,section='Chapter Two',count=3)
            self.assertEqual(second[0]['text'],'Chapter Two')
            self.assertIn('    print(x)',second[1]['text'])
            self.assertEqual(library.lookup(out,paragraph=second[2]['paragraph'])[0]['text'],'Second paragraph.')
            self.assertFalse(library.lookup(out,query='Not body'))
            image=library.lookup(out,query='A diagram')[0]
            self.assertEqual(image['assets'],['OPS/image.png'])
    def test_local_only_safe_paths_and_drm(self):
        for href in ['../../escape','https://example.com/image.png','javascript:alert(1)']:
            with self.assertRaises(ValueError):library.resolve('OPS/book.opf',href)
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'book.epub';fixture(source,encrypted=True)
            with self.assertRaisesRegex(ValueError,'Encrypted'):library.prepare(source,Path(temp)/'out')
    def test_resume_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'book.epub';fixture(source)
            out=Path(temp)/'out';library.prepare(source,out)
            with self.assertRaisesRegex(ValueError,'not empty'):library.prepare(source,out)
    def test_large_index_and_text_remain_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'book.epub'
            fixture(source,'<h1 id="one">One</h1>'+''.join('<p>Text '+str(i)+' '+('long content '*20)+'</p>' for i in range(6500))+'<h1 id="two">Two</h1><p>Last paragraph</p>')
            out=Path(temp)/'out';plan=library.prepare(source,out)
            index=json.loads((out/'index.json').read_text())
            self.assertTrue(index['index_parts'])
            self.assertLessEqual((out/'index.json').stat().st_size,1024*1024)
            self.assertTrue(all((out/f['file']).stat().st_size<=library.MAX_TEXT for f in index['text_chunks']+index['index_parts']))
            self.assertTrue(library.lookup(out,query='Text 6499'))
            self.assertEqual(library.lookup(out,query='Last paragraph')[0]['text'],'Last paragraph')

if __name__=='__main__':unittest.main()


import json
import tempfile
import unittest
from pathlib import Path
from repofix.tools import RepositoryTools
from test_core import TrustedFixtureRunner


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'main.py').write_text('value = 1\nvalue = 1\n')
        self.tools=RepositoryTools(TrustedFixtureRunner(self.root),mode='structured')

    def test_search_and_line_read(self):
        found=json.loads(self.tools.execute('search_text',{'query':'value'})['output'])
        self.assertEqual([match['line'] for match in found['matches']],[1,2])
        result=json.loads(self.tools.execute('read_file',{'path':'main.py','start_line':2,'line_count':1})['output'])
        self.assertEqual(result['lines'],['2: value = 1'])

    def test_ambiguous_edit_fails_without_modifying_file(self):
        result=self.tools.execute('replace_text',{'path':'main.py','old':'value = 1','new':'value = 2'})
        self.assertNotEqual(result['exit_code'],0)
        self.assertEqual((self.root/'main.py').read_text(),'value = 1\nvalue = 1\n')
        self.assertEqual(self.tools.execute('replace_text',{'path':'main.py','old':'value = 1','new':'value = 2','expected_count':2})['exit_code'],0)

    def test_path_escape_private_files_and_schema_violations(self):
        for name in ('../outside','/etc/passwd','.git/config','.env'):
            with self.subTest(name=name):
                self.assertNotEqual(self.tools.execute('read_file',{'path':name})['exit_code'],0)
        for name,args in [('read_file',{'path':'main.py','line_count':True}),('read_file',{'path':'main.py','extra':'bad'}),('unknown',{})]:
            with self.subTest(name=name),self.assertRaises(ValueError):
                self.tools.execute(name,args)

    def test_list_hides_environment_files_and_symlinks(self):
        (self.root/'.env').write_text('private')
        (self.root/'link').symlink_to('/etc/passwd')
        output=json.loads(self.tools.execute('list_files',{})['output'])
        self.assertEqual(output['files'],['main.py'])

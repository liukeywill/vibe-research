"""Endpoint regression tests with synthetic fixtures, never research output."""
import contextlib,io,json,tempfile,unittest,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
import manuscript,pipeline,workspace,paper_request

class ManuscriptGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        def save(n,obj): (self.root/n).parent.mkdir(parents=True,exist_ok=True);(self.root/n).write_text(json.dumps(obj))
        self.save=save
        save('pipeline-state.json',{'deliverable_profile':'manuscript'})
        save('research/sources.json',[{'id':'S1','url':'https://example.org/source','metadata_status':'verified','access_level':'fulltext'}])
        save('report.json',{'claims':[{'id':'C1','status':'supported','evidence_ids':['E1']}]})
        save('research/evidence.json',[{'id':'E1','source_id':'S1'}])
        save('research/analysis-result.json',{'status':'planned'})
        self.paper={'schema_version':1,'id':'fixture','title':'Synthetic manuscript fixture','paper_type':'conceptual','abstract':'A synthetic fixture for manuscript endpoint checks. '*5,'keywords':['fixture','test','draft'],'sections':[{'id':'s'+str(i),'heading':role,'role':role,'paragraphs':[{'id':'p'+str(i),'text':'This is synthetic test material for validating a complete manuscript delivery boundary. '*4,'stance':'source_fact','source_ids':['S1'],'claim_ids':['C1']}]}for i,role in enumerate(sorted(manuscript.ROLES))],'references':[{'source_id':'S1','citation':'Synthetic author. Synthetic source for tests.','url':'https://example.org/source'}]}
    def tearDown(self):self.tmp.cleanup()
    def deliver(self):
        self.save('manuscript.json',self.paper);manuscript.render(self.root)
        ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main';doc=ET.Element('{'+ns+'}document');body=ET.SubElement(doc,'{'+ns+'}body')
        for text in manuscript.paragraphs(self.paper,paper_request.language(self.root)):
            p=ET.SubElement(body,'{'+ns+'}p');r=ET.SubElement(p,'{'+ns+'}r');ET.SubElement(r,'{'+ns+'}t').text=text
        with zipfile.ZipFile(self.root/'manuscript.docx','w')as z:z.writestr('word/document.xml',ET.tostring(doc))
    def test_cli_defaults_to_paper_but_existing_state_keeps_report(self):
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(pipeline.main(['init','--project',str(self.root/'new'),'--topic','fixture']),0)
        state=pipeline.load(self.root/'new');self.assertIn('manuscript.docx',pipeline.outputs('package',state));self.assertNotIn('manuscript.docx',pipeline.outputs('package',{'profile':'structured'}))
    def test_complete_paper_and_docx_drift(self):
        self.deliver();self.assertEqual(manuscript.validate_project(self.root)['references'],1)
        with zipfile.ZipFile(self.root/'manuscript.docx','w')as z:z.writestr('word/document.xml','<document/>')
        with self.assertRaises(workspace.WorkspaceError):manuscript.validate_project(self.root)
    def test_report_without_manuscript_is_rejected(self):
        with self.assertRaises(OSError):manuscript.validate_project(self.root)
    def test_unexecuted_empirical_paper_is_rejected(self):
        self.paper['paper_type']='empirical'
        with self.assertRaises(ValueError):manuscript.validate_content(self.root,self.paper)
    def test_hypothesis_cannot_be_relabelled_source_fact(self):
        self.save('report.json',{'claims':[{'id':'C1','status':'hypothesis','evidence_ids':['E1']}]})
        with self.assertRaises(workspace.WorkspaceError):manuscript.validate_content(self.root,self.paper)
    def test_outline_only_is_rejected(self):
        self.paper['sections']=self.paper['sections'][:1]
        with self.assertRaises(ValueError):manuscript.validate_content(self.root,self.paper)
    def test_requested_length_is_enforced_at_delivery(self):
        value=paper_request.normalize({'topic':'fixture','length':1000})
        self.save('project-spec.json',{'topic':'fixture','language':'zh-CN','constraints':['paper_request:'+json.dumps(value)]})
        for section in self.paper['sections']:section['paragraphs'][0]['text']='甲'*200
        self.deliver()
        self.assertEqual(manuscript.validate_project(self.root)['body_length'],1000)
        value['length']=2000
        self.save('project-spec.json',{'topic':'fixture','language':'zh-CN','constraints':['paper_request:'+json.dumps(value)]})
        with self.assertRaises(workspace.WorkspaceError):manuscript.validate_project(self.root)
    def test_english_counts_words_and_delivers_english_apparatus(self):
        value=paper_request.normalize({'topic':'fixture','length':1000,'language':'英文'})
        self.save('project-spec.json',{'topic':'fixture','language':'en','constraints':['paper_request:'+json.dumps(value)]})
        for section in self.paper['sections']:section['paragraphs'][0]['text']='word '*200
        self.deliver()
        result=manuscript.validate_project(self.root)
        self.assertEqual(result['length_unit'],'words');self.assertEqual(result['body_length'],1000)
        self.assertIn('## Abstract',(self.root/'manuscript.md').read_text())
    def test_conflicting_input_contract_is_rejected(self):
        value=paper_request.normalize({'topic':'other','length':1000})
        self.save('project-spec.json',{'topic':'fixture','language':'zh-CN','constraints':['paper_request:'+json.dumps(value)]})
        with self.assertRaises(workspace.WorkspaceError):manuscript.validate_content(self.root,self.paper)
    def test_request_defaults_and_invalid_lengths(self):
        self.assertEqual(paper_request.normalize({'topic':'fixture'})['length'],8000)
        for length in (True,999,'8000'):
            with self.assertRaises(workspace.WorkspaceError):paper_request.normalize({'topic':'fixture','length':length})

if __name__=='__main__':unittest.main()

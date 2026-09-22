import unittest
from unittest.mock import patch,Mock
from pocs.inspection.core import make_batch,payload,rule_decision,metrics,decide
from pocs.inspection.app import finalize

class InspectionTests(unittest.TestCase):
    def test_generated_cases_match_spec_and_do_not_leak_answers(self):
        for seed in range(20):
            items=make_batch(seed)
            self.assertEqual(items,make_batch(seed))
            for item in items:
                state=payload(item)
                self.assertNotIn('expected',state);self.assertNotIn('case',state)
                self.assertEqual(rule_decision(state)[0],item['expected'])
    def test_grade_boundary_and_missing_precedence(self):
        item=make_batch()[0];item['measurements']={'width_mm':50.5,'weight_g':97,'scratch_mm':0.3,'color_delta':2,'label_ok':True}
        item['specification'].update(scratch_mm_max=0.3,color_delta_max=2)
        self.assertEqual(rule_decision(item)[0],'pass')
        item['measurements']['weight_g']=None
        self.assertEqual(rule_decision(item)[0],'review')
        item['measurements']['scratch_mm']=0.31
        self.assertEqual(rule_decision(item)[0],'reject')
    def test_late_response_cannot_change_sorting(self):
        r={'born':0,'baseline':'reject','answer':{'verdict':'pass'},'received':4.1}
        finalize(r,4.2);self.assertEqual(r['route'],'review')
        r['answer']['verdict']='reject';finalize(r,5)
        self.assertEqual(r['route'],'review')
    def test_metrics_separate_review_from_misses(self):
        rows=[{'finalized':True,'route':'review','item':{'expected':'reject'}},
              {'finalized':True,'route':'pass','item':{'expected':'reject'}},
              {'finalized':True,'route':'reject','item':{'expected':'pass'}}]
        result=metrics(rows,'route')
        self.assertEqual(result['misses'],1);self.assertEqual(result['false_rejects'],1)
        self.assertEqual(result['review'],1)
    def test_api_validation_and_error_handling(self):
        response=Mock(status_code=200)
        response.json.return_value={'answers':{'verdict':{'choice':'invented'}}}
        with patch('pocs.inspection.core.requests.post',return_value=response):
            result=decide('synthetic',payload(make_batch()[0]))
        self.assertIn('error',result);self.assertNotIn('verdict',result)
        response.status_code=429
        with patch('pocs.inspection.core.requests.post',return_value=response):
            self.assertTrue(decide('synthetic',{})['fatal'])

if __name__=='__main__':unittest.main()

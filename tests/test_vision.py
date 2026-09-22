import unittest
from unittest.mock import patch,Mock
import numpy as np
from pocs.vision.model import features,Detector,decision_state
from pocs.vision.app import ask,summary

class VisionTests(unittest.TestCase):
    def test_training_and_calibration_do_not_read_test_images(self):
        paths=[]
        def read(path):
            paths.append(str(path).replace('\\','/'))
            return np.full((128,128,3),0.5,dtype=np.float32)
        with patch('pocs.vision.model.pixels',side_effect=read):detector=Detector()
        self.assertEqual(len(paths),40)
        self.assertTrue(all('/train/good/' in p for p in paths))
        self.assertEqual(features(read('synthetic')).shape,(32,32,8))
        changed=read('synthetic');changed[40:60,40:60]=0
        anomaly=detector.map(changed)
        self.assertGreater(anomaly[10:15,10:15].mean(),anomaly[:5,:5].mean())
    def test_api_state_does_not_include_ground_truth_or_file(self):
        result={'features':{'score_ratio':1.3},'path':'broken_large/000.png','ground_truth':'reject','local_verdict':'reject'}
        state=decision_state(result)
        self.assertEqual(set(state),{'sensor','features','inspection_rules'})
        self.assertNotIn('broken_large',str(state));self.assertNotIn('local_verdict',str(state))
    def test_response_is_validated(self):
        response=Mock(status_code=200)
        response.json.return_value={'answers':{'route':{'choice':'unknown'}}}
        with patch('pocs.vision.app.requests.post',return_value=response):
            self.assertIn('error',ask('synthetic',{}))
    def test_evaluation_counts_errors_and_ties(self):
        rows=[]
        for kind,score in [('good',1.1),('broken_large',1.1)]:
            rows.append({'kind':kind,'result':{'features':{'score_ratio':score},'local_verdict':'review','vision_ms':1},'mask_iou':0.5})
        result=summary(rows)
        self.assertEqual(result['image_auroc'],0.5);self.assertEqual(result['binary_false_rejects'],1)
        self.assertEqual(result['binary_misses'],0)

if __name__=='__main__':unittest.main()

"""CPU nearest-normal patch features. No deep network or semantic defect labels."""
import time
import numpy as np
from PIL import Image
from .data import DATA

SIZE=128
GRID=32

def pixels(path):
    with Image.open(path) as im:return np.asarray(im.convert('RGB').resize((SIZE,SIZE)),dtype=np.float32)/255

def features(rgb):
    cells=rgb.reshape(GRID,4,GRID,4,3)
    mean=cells.mean(axis=(1,3));std=cells.std(axis=(1,3))
    gray=rgb.mean(axis=2);gy,gx=np.gradient(gray)
    grad=np.stack([abs(gx),abs(gy)],axis=2).reshape(GRID,4,GRID,4,2).mean(axis=(1,3))
    return np.concatenate([mean,std,grad],axis=2)

class Detector:
    def __init__(self):
        # Fixed train/calibration split; no test image or annotation is used here.
        self.bank=np.stack([features(pixels(DATA/f'train/good/{i:03d}.png')) for i in range(30)])
        self.scale=np.maximum(self.bank.std(axis=(0,1,2)),0.03)
        calibration=[self.map(pixels(DATA/f'train/good/{i:03d}.png')) for i in range(30,40)]
        self.pixel_threshold=float(np.quantile(np.stack(calibration),0.995))
        self.image_threshold=max(float(max(self.score(m) for m in calibration))*1.1,1e-6)
    @staticmethod
    def score(anomaly):return float(np.sort(anomaly.ravel())[-11:].mean())
    def map(self,rgb):
        f=features(rgb);best=np.full((GRID,GRID),np.inf,dtype=np.float32)
        # Compare patches with normal examples at this position and its neighbours.
        padded=np.pad(self.bank,((0,0),(1,1),(1,1),(0,0)),mode='edge')
        for dy in range(3):
            for dx in range(3):
                delta=(padded[:,dy:dy+GRID,dx:dx+GRID]-f)/self.scale
                best=np.minimum(best,np.sqrt((delta*delta).mean(axis=3)).min(axis=0))
        return best
    def inspect(self,path):
        start=time.perf_counter();rgb=pixels(path);anomaly=self.map(rgb);score=self.score(anomaly)
        ratio=round(score/self.image_threshold,4)
        decision='reject' if ratio>1.2 else 'review' if ratio>=0.8 else 'pass'
        return {'rgb':rgb,'map':anomaly,'features':{'anomaly_score':round(score,6),
            'normal_calibrated_threshold':round(self.image_threshold,6),'score_ratio':round(ratio,4),
            'anomalous_patch_percent':round(float((anomaly>self.pixel_threshold).mean()*100),2),
            'pixel_threshold':round(self.pixel_threshold,6)},'local_verdict':decision,
            'vision_ms':round((time.perf_counter()-start)*1000,1)}

def decision_state(result):
    # No source filename, defect class, ground-truth mask or label leaves the evaluator.
    return {'sensor':'Local normal-reference patch anomaly detector (not semantic recognition)',
        'features':result['features'],'inspection_rules':
        'score_ratio > 1.2: reject. score_ratio < 0.8: pass. Otherwise: review. '
        'Apply these inclusive review boundaries exactly. Scores are heuristic, not probabilities. '
        'Images and ground truth are unavailable. This is a downstream routing decision only.'}

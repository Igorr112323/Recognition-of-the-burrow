from pathlib import Path
import os
import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from nets.retinanet import retinanet
from utils.utils import resize_image, preprocess_input
from utils.utils_bbox import decodebox, non_max_suppression
from download_model import PATH, verify

FONT = Path(__file__).resolve().parent / 'assets/fonts/DejaVuSans.ttf'

class Detector:
    def __init__(self):
        ok, error = verify()
        if not ok:
            raise ValueError(error)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        if self.device.type == 'cpu':
            try:
                cores = len(os.sched_getaffinity(0))
            except AttributeError:
                cores = os.cpu_count() or 2
            torch.set_num_threads(max(1, min(4, cores - 1)))
        net = retinanet(num_classes=1, phi=5, pretrained=False)
        try:
            weights = torch.load(PATH, map_location=self.device, weights_only=True)
        except TypeError:
            weights = torch.load(PATH, map_location=self.device)
        net.load_state_dict(weights, strict=True)
        self.net = net.to(self.device).eval()

    def detect(self, frame, size, confidence):
        h, w = frame.shape[:2]
        rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        image = resize_image(rgb, (size, size), True)
        data = preprocess_input(np.array(image, dtype=np.float32))
        data = torch.from_numpy(np.transpose(data, (2, 0, 1))[None]).to(self.device)
        with torch.inference_mode():
            _, regression, classification, anchors = self.net(data)
            boxes = decodebox(regression, anchors, [size, size])
            result = non_max_suppression(torch.cat((boxes, classification), dim=-1), [size, size], [h, w], True, confidence, 0.3)[0]
        if result is None:
            return []
        found = []
        for top, left, bottom, right, score, _ in result:
            x1, y1 = max(0, min(w-1, int(left))), max(0, min(h-1, int(top)))
            x2, y2 = max(0, min(w-1, int(right))), max(0, min(h-1, int(bottom)))
            if x2 > x1 and y2 > y1:
                found.append((x1, y1, x2, y2, float(score)))
        return found


def draw(frame, boxes):
    if not boxes:
        return frame
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    canvas = ImageDraw.Draw(image)
    w, h = image.size
    font = ImageFont.truetype(str(FONT), max(12, min(36, h // 25)))
    for x1, y1, x2, y2, score in boxes:
        canvas.rectangle((x1, y1, x2, y2), outline=(255, 230, 0), width=max(2, h // 300))
        label = f'Нора {score:.0%}'
        bbox = canvas.textbbox((0, 0), label, font=font)
        tw, th = bbox[2]-bbox[0]+8, bbox[3]-bbox[1]+6
        x = max(0, min(x1, w-tw)); y = max(0, min(y1-th, h-th))
        canvas.rectangle((x, y, min(w-1, x+tw), min(h-1, y+th)), fill=(255, 230, 0))
        canvas.text((x+4, y+3-bbox[1]), label, font=font, fill=(20, 20, 20))
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
